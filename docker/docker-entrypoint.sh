#!/bin/bash
set -e

# Enhanced Squid Docker Entrypoint Script
# Handles initialization and configuration for range forwarding feature

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to initialize squid cache
init_cache() {
    if [ ! -d "$SQUID_CACHE_DIR/00" ]; then
        log "Initializing Squid cache directories..."
        /usr/sbin/squid -z -f "$SQUID_CONFIG_FILE"
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

# Function to set proper permissions
set_permissions() {
    # Ensure proxy user owns necessary directories
    chown -R proxy:proxy "$SQUID_CACHE_DIR" "$SQUID_LOG_DIR"
    
    # Ensure config file is readable
    chown proxy:proxy "$SQUID_CONFIG_FILE"
    chmod 644 "$SQUID_CONFIG_FILE"
}

# Main initialization
main() {
    log "Starting Enhanced Squid with Range Forwarding..."
    log "Configuration file: $SQUID_CONFIG_FILE"
    log "Cache directory: $SQUID_CACHE_DIR"
    log "Log directory: $SQUID_LOG_DIR"
    log "Range forwarding: ${RANGE_FORWARD:-on}"
    
    # Set proper permissions
    set_permissions
    
    # Configure range forwarding
    configure_range_forwarding
    
    # Validate configuration
    validate_config
    
    # Initialize cache if needed
    init_cache
    
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