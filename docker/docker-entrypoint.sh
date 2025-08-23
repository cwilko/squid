#!/bin/bash
set -e

# Enhanced Squid Docker Entrypoint Script
# Handles initialization and configuration for range forwarding feature

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to clean up stale PID files and processes
cleanup_squid_processes() {
    local pid_file="/var/run/squid.pid"
    
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        log "Found PID file with PID: $pid"
        
        # Check if the process is actually running
        if kill -0 "$pid" 2>/dev/null; then
            log "Squid process $pid is still running, waiting for it to finish..."
            # Wait up to 30 seconds for the process to finish
            local count=0
            while kill -0 "$pid" 2>/dev/null && [ $count -lt 30 ]; do
                sleep 1
                count=$((count + 1))
            done
            
            if kill -0 "$pid" 2>/dev/null; then
                log "Process $pid did not finish, terminating it..."
                kill -TERM "$pid" 2>/dev/null || true
                sleep 2
                if kill -0 "$pid" 2>/dev/null; then
                    log "Force killing process $pid..."
                    kill -KILL "$pid" 2>/dev/null || true
                fi
            fi
        fi
        
        log "Removing stale PID file: $pid_file"
        rm -f "$pid_file"
    fi
    
    # Also clean up any other squid processes that might be running
    if pgrep -f "/usr/sbin/squid" >/dev/null; then
        log "Found other squid processes, cleaning up..."
        pkill -f "/usr/sbin/squid" || true
        sleep 2
    fi
}

# Function to clean up old prefetch files
cleanup_prefetch_files() {
    local log_dir="$SQUID_LOG_DIR"
    
    if [ -d "$log_dir" ]; then
        log "Cleaning up old prefetch files in $log_dir..."
        
        # Remove old prefetch state files
        if [ -f "$log_dir/squid_prefetch.lock" ]; then
            log "Removing stale prefetch lock file"
            rm -f "$log_dir/squid_prefetch.lock"
        fi
        
        if [ -f "$log_dir/squid_prefetch.pid" ]; then
            log "Removing stale prefetch PID file"
            rm -f "$log_dir/squid_prefetch.pid"
        fi
        
        # Remove ALL wget log files (clean slate on startup)
        if find "$log_dir" -name "wget_progress_*.log" -type f -print -quit 2>/dev/null | grep -q .; then
            log "Removing all existing wget log files"
            find "$log_dir" -name "wget_progress_*.log" -type f -delete 2>/dev/null || true
        fi
        
        log "Prefetch file cleanup completed"
    else
        log "Log directory $log_dir does not exist, skipping prefetch cleanup"
    fi
}

# Function to clean up squid cache contents
cleanup_cache_contents() {
    # Check environment variable (default is 'on' - cleanup enabled)
    local cleanup_enabled="${SQUID_CLEANUP_CACHE_ON_START:-on}"
    
    if [ "$cleanup_enabled" = "off" ] || [ "$cleanup_enabled" = "false" ] || [ "$cleanup_enabled" = "no" ]; then
        log "Cache cleanup disabled by SQUID_CLEANUP_CACHE_ON_START environment variable"
        return 0
    fi
    
    # Determine cache directory from SQUID_CACHE_DIR or default
    local cache_dir="${SQUID_CACHE_DIR:-/var/spool/squid}"
    
    if [ -d "$cache_dir" ]; then
        log "Wiping all contents in $cache_dir..."
        
        # Count items before removal
        local content_count=$(find "$cache_dir" -mindepth 1 2>/dev/null | wc -l || echo "0")
        
        if [ "$content_count" -gt 0 ]; then
            log "Removing $content_count items (files and directories) from cache"
            # Remove everything inside the cache directory (files, folders, hidden files)
            rm -rf "$cache_dir"/{*,.[^.]*,..?*} 2>/dev/null || {
                log "WARNING: Some cache items could not be removed"
            }
            log "Cache wipe completed"
        else
            log "Cache directory is already empty"
        fi
        
        # Ensure proper ownership and permissions of the empty cache directory
        chown proxy:proxy "$cache_dir" 2>/dev/null || true
        chmod 755 "$cache_dir" 2>/dev/null || true
        
    else
        log "Cache directory $cache_dir does not exist yet, skipping cache cleanup"
    fi
}

# Function to create symlinks for kubectl logs
create_kubectl_log_symlinks() {
    local log_dir="$SQUID_LOG_DIR"
    
    log "Creating symlinks for kubectl logs..."
    
    # Ensure log directory exists and has proper ownership
    mkdir -p "$log_dir"
    chown -R proxy:proxy "$log_dir"
    chmod 755 "$log_dir"
    
    # Clean up any existing named pipe (important for mounted volumes)
    if [ -p "$log_dir/stdout_pipe" ]; then
        log "Removing existing named pipe: $log_dir/stdout_pipe"
        rm -f "$log_dir/stdout_pipe"
    fi
    
    # Create symlink for squid access logs to stdout
    ln -sf /proc/self/fd/1 "$log_dir/stdout.log"
    chown proxy:proxy "$log_dir/stdout.log"
    
    # Create named pipe for store ID logs
    mkfifo "$log_dir/stdout_pipe"
    chown proxy:proxy "$log_dir/stdout_pipe"
    chmod 666 "$log_dir/stdout_pipe"
    
    # Start background process to forward pipe content to stdout
    nohup sh -c 'while true; do cat '"$log_dir"'/stdout_pipe || sleep 1; done' >&1 2>/dev/null &
    
    log "Logging infrastructure created:"
    log "  $log_dir/stdout.log -> symlink to stdout (for squid access logs)"
    log "  $log_dir/stdout_pipe -> named pipe forwarded to stdout (for store ID logs)"
}

# Function to configure wget to use Squid proxy
configure_wget_proxy() {
    local wgetrc="/etc/wgetrc"
    
    log "Configuring wget to use Squid proxy..."
    
    # Check if proxy configuration already exists
    if [ -f "$wgetrc" ] && grep -q "http_proxy.*127.0.0.1:3128" "$wgetrc" 2>/dev/null; then
        log "wget proxy configuration already exists"
        return 0
    fi
    
    # Add or update proxy configuration
    {
        echo ""
        echo "# Squid proxy configuration (added by container)"
        echo "http_proxy = http://127.0.0.1:3128"
        echo "https_proxy = http://127.0.0.1:3128"
        echo "ftp_proxy = http://127.0.0.1:3128"
        echo "use_proxy = on"
    } >> "$wgetrc"
    
    log "wget proxy configuration completed"
}

# Function to initialize squid cache
init_cache() {
    if [ ! -d "$SQUID_CACHE_DIR/00" ]; then
        log "Initializing Squid cache directories..."
        /usr/sbin/squid -z -f "$SQUID_CONFIG_FILE"
        log "Cache initialization completed, cleaning up any processes..."
        cleanup_squid_processes
    else
        log "Cache directories already exist"
    fi
}

# Function to configure range forwarding based on environment
configure_range_forwarding() {
    local config_file="$SQUID_CONFIG_FILE"
    
    # Check if range_forward_on_cache_miss is already configured
    if ! grep -q "range_forward_on_cache_miss" "$config_file"; then
        log "Adding range forwarding configuration..."
        echo "" >> "$config_file"
        echo "# Enhanced Range Forwarding Feature (added by container)" >> "$config_file"
        echo "range_forward_on_cache_miss ${RANGE_FORWARD:-on}" >> "$config_file"
    else
        # Update existing configuration
        if [ "$RANGE_FORWARD" != "on" ] && [ "$RANGE_FORWARD" != "off" ]; then
            RANGE_FORWARD="on"
        fi
        log "Updating range forwarding setting to: $RANGE_FORWARD"
        sed -i "s/^range_forward_on_cache_miss.*/range_forward_on_cache_miss $RANGE_FORWARD/" "$config_file"
    fi
}

# Function to validate configuration
validate_config() {
    log "Validating Squid configuration..."
    if ! /usr/sbin/squid -k parse -f "$SQUID_CONFIG_FILE"; then
        log "ERROR: Invalid Squid configuration!"
        exit 1
    fi
    log "Configuration is valid"
}

# Function to fix mounted volume permissions
fix_mounted_volume_permissions() {
    # Fix permissions for commonly mounted directories
    local potential_dirs=("/var/cache/squid" "/var/spool/squid" "$SQUID_LOG_DIR")
    
    for dir in "${potential_dirs[@]}"; do
        if [ -d "$dir" ]; then
            log "Fixing permissions for mounted directory: $dir"
            chown -R proxy:proxy "$dir"
            chmod 755 "$dir"
            # Make scripts executable
            find "$dir" -name "*.py" -exec chmod +x {} \; 2>/dev/null || true
        fi
    done
    
    # Skip /etc/squid permissions - mounted as read-only ConfigMaps/secrets
}

# Function to copy required config files if missing (for mounted volumes)
copy_required_configs() {
    local config_dir="$(dirname "$SQUID_CONFIG_FILE")"
    
    # Copy mime.conf if it doesn't exist
    if [ ! -f "$config_dir/mime.conf" ]; then
        log "Copying missing mime.conf to mounted volume..."
        cp /usr/share/squid/conf-defaults/mime.conf "$config_dir/mime.conf"
    fi
    
    # Create default squid.conf if it doesn't exist
    if [ ! -f "$SQUID_CONFIG_FILE" ]; then
        log "Creating default squid.conf in mounted volume..."
        cat > "$SQUID_CONFIG_FILE" << 'EOF'
# Enhanced Squid with Range Forwarding
http_port 3128

# Disable ICMP pinger (not needed in container environment)
pinger_enable off

# ACLs
acl localnet src 10.0.0.0/8
acl localnet src 172.16.0.0/12
acl localnet src 192.168.0.0/16
acl SSL_ports port 443
acl Safe_ports port 80
acl Safe_ports port 443
acl CONNECT method CONNECT

# Access rules
http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow localhost manager
http_access deny manager
http_access allow localnet
http_access allow localhost
http_access deny all

# Enhanced Range Forwarding Feature
range_forward_on_cache_miss on

# Cache configuration
cache_dir ufs /var/cache/squid 1000 16 256
maximum_object_size 1 GB
cache_mem 256 MB
EOF
    fi
}

# Function to initialize SSL certificate database
init_ssl_db() {
    local ssl_db_dir="/var/lib/squid/ssl_db"
    local ssl_helper="/usr/lib/squid/security_file_certgen"
    
    # Check if SSL helper exists and has proper permissions
    if [ ! -f "$ssl_helper" ]; then
        log "WARNING: SSL certificate helper not found at $ssl_helper"
        return 0
    fi
    
    # Ensure helper has proper permissions
    chown root:proxy "$ssl_helper"
    chmod 4755 "$ssl_helper"
    
    if [ ! -d "$ssl_db_dir" ]; then
        log "Initializing SSL certificate database..."
        mkdir -p /var/lib/squid
        chown proxy:proxy /var/lib/squid
        
        # Initialize SSL database as proxy user
        log "Running SSL database initialization command: sudo -u proxy $ssl_helper -c -s $ssl_db_dir -M 4MB"
        log "Current /var/lib/squid permissions: $(ls -la /var/lib/ | grep squid || echo 'directory does not exist')"
        log "SSL helper permissions: $(ls -la $ssl_helper)"
        
        if sudo -u proxy "$ssl_helper" -c -s "$ssl_db_dir" -M 4MB 2>&1 | while read line; do log "SSL init: $line"; done; then
            log "SSL database initialized successfully"
            chown -R proxy:proxy /var/lib/squid
            log "SSL database final permissions: $(ls -la /var/lib/squid/)"
        else
            log "ERROR: Failed to initialize SSL database"
            log "Checking if sudo is available: $(which sudo || echo 'sudo not found')"
            log "Checking if proxy user exists: $(id proxy 2>&1 || echo 'proxy user not found')"
            log "Trying direct execution without sudo..."
            if "$ssl_helper" -c -s "$ssl_db_dir" -M 4MB 2>&1 | while read line; do log "SSL direct: $line"; done; then
                log "SSL database initialized successfully with direct execution"
                chown -R proxy:proxy /var/lib/squid
            else
                log "ERROR: Both sudo and direct execution failed for SSL database initialization"
            fi
        fi
    else
        log "SSL certificate database already exists"
        # Ensure proper ownership
        chown -R proxy:proxy "$ssl_db_dir"
    fi
}

# Function to start metrics API
start_metrics_api() {
    log "Starting Squid Metrics API..."
    nohup python3 /usr/local/bin/squid_metrics_api.py > /var/log/squid/metrics_api.log 2>&1 &
    local api_pid=$!
    echo $api_pid > /var/run/squid_metrics_api.pid
    log "Metrics API started with PID: $api_pid"
}

# Function to set proper permissions
set_permissions() {
    # Ensure proxy user owns necessary directories
    chown -R proxy:proxy "$SQUID_CACHE_DIR" "$SQUID_LOG_DIR" /var/spool/squid /var/lib/squid
    
    # Create and set permissions for PID file directory
    mkdir -p /var/run/squid
    chown proxy:proxy /var/run /var/run/squid
    chmod 755 /var/run/squid
    
    # Skip config file permissions - mounted as read-only ConfigMaps
}

# Main initialization
main() {
    log "Starting Enhanced Squid with Range Forwarding..."
    log "Configuration file: $SQUID_CONFIG_FILE"
    log "Cache directory: $SQUID_CACHE_DIR"
    log "Log directory: $SQUID_LOG_DIR"
    log "Range forwarding: ${RANGE_FORWARD:-on}"
    
    # Copy required config files if missing (handles mounted volumes)
    copy_required_configs
    
    # Fix mounted volume permissions (critical for volume mounts)
    fix_mounted_volume_permissions
    
    # Set proper permissions
    set_permissions
    
    # Clean up old prefetch files
    cleanup_prefetch_files
    
    # Create logging infrastructure for kubectl logs
    create_kubectl_log_symlinks
    
    # Configure wget to use Squid proxy
    configure_wget_proxy
    
    # Initialize SSL database
    init_ssl_db
    
    # Configure range forwarding
    configure_range_forwarding
    
    # Validate configuration
    validate_config
    
    # Clean up cache contents if enabled
    cleanup_cache_contents
    
    # Initialize cache if needed
    init_cache
    
    # Start metrics API
    start_metrics_api
    
    # Final cleanup before starting main Squid process
    log "Performing final cleanup before starting Squid..."
    cleanup_squid_processes
    
    log "Initialization complete. Starting Squid..."
}

# Handle special commands
case "$1" in
    "init")
        # Just initialize cache and exit
        main
        log "Initialization only mode - exiting"
        exit 0
        ;;
    "config-check")
        # Just validate config and exit
        validate_config
        log "Configuration check passed"
        exit 0
        ;;
    "/usr/sbin/squid"|"squid")
        # Normal startup
        main
        ;;
    *)
        # If first argument doesn't look like squid command, run initialization
        if [[ "$1" != -* ]] && [ "$1" != "/usr/sbin/squid" ]; then
            log "Custom command detected: $*"
            exec "$@"
        else
            main
        fi
        ;;
esac

# If we get here, execute the provided command
exec "$@"