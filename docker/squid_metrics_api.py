#!/usr/bin/env python3
"""
Squid Cache Metrics REST API

Provides HTTP endpoints for retrieving Squid proxy cache metrics.
"""

import subprocess
import json
import logging
import re
import os
import time
import requests
from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

# Configure logging
LOG_LEVEL = os.environ.get('SQUID_API_LOG_LEVEL', 'INFO').upper()
log_level_mapping = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}
logging.basicConfig(level=log_level_mapping.get(LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

# File size cache - stores URL -> file_size_mb mappings
file_size_cache = {}

# Cache for configured cache size from squid.conf
configured_cache_size_mb = None

def run_command(command, log_errors=True):
    """Execute a shell command and return the output"""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            if log_errors:
                logger.error(f"Command failed: {command}, Error: {result.stderr}")
            else:
                logger.debug(f"Command returned no results: {command}")
            return None
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out: {command}")
        return None
    except Exception as e:
        logger.error(f"Command execution error: {command}, Exception: {e}")
        return None

def get_file_size(url):
    """Get file size in MB for a given URL using HEAD request"""
    # Check cache first
    if url in file_size_cache:
        logger.info(f"File size cache hit for URL: {url}")
        return file_size_cache[url]
    
    try:
        # Use Python requests for HEAD request (no proxy, ignore SSL issues)
        response = requests.head(
            url,
            timeout=30,
            verify=False,  # Ignore SSL certificate issues
            allow_redirects=True,
            headers={'User-Agent': 'Squid-Metrics-API/1.0'}
        )
        
        # Check if request was successful
        response.raise_for_status()
        
        # Get Content-Length header
        content_length = response.headers.get('content-length')
        if content_length:
            try:
                size_bytes = int(content_length)
                size_mb = round(size_bytes / (1024 * 1024), 2)
                
                # Cache the result
                file_size_cache[url] = size_mb
                logger.info(f"File size cached for URL: {url} = {size_mb} MB")
                return size_mb
            except ValueError:
                logger.error(f"Invalid Content-Length value: {content_length}")
        else:
            logger.warning(f"No Content-Length header found for URL: {url}")
        
        return None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get file size for URL {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting file size for URL {url}: {e}")
        return None

def get_configured_cache_size():
    """Get configured cache size from squid.conf file"""
    global configured_cache_size_mb
    
    # Return cached value if available
    if configured_cache_size_mb is not None:
        logger.info(f"Configured cache size cache hit: {configured_cache_size_mb} MB")
        return configured_cache_size_mb
    
    try:
        squid_conf_path = '/etc/squid/squid.conf'
        if not os.path.exists(squid_conf_path):
            logger.warning(f"Squid config file not found: {squid_conf_path}")
            return None
        
        with open(squid_conf_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Look for cache_dir directive
                if line.startswith('cache_dir') and not line.startswith('#'):
                    # Format: cache_dir type path size_mb L1 L2
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            size_mb = int(parts[3])
                            configured_cache_size_mb = size_mb
                            logger.info(f"Configured cache size cached: {size_mb} MB")
                            return size_mb
                        except ValueError:
                            logger.error(f"Invalid cache_dir size in config: {parts[3]}")
                            continue
        
        logger.warning("No cache_dir directive found in squid.conf")
        configured_cache_size_mb = 0  # Cache the fact that we couldn't find it
        return None
        
    except Exception as e:
        logger.error(f"Error reading squid.conf: {e}")
        return None

def parse_curl_completion_log(log_file_path):
    """Parse curl completion log to extract final statistics"""
    try:
        with open(log_file_path, 'r') as f:
            content = f.read()
            
        # Look for the FINAL line from --write-out
        # Format: FINAL: HTTP 200 | 1073741824 bytes | 180.5s | 5962370 bytes/s avg
        for line in content.split('\n'):
            if line.startswith('FINAL:'):
                parts = line.split('|')
                if len(parts) >= 4:
                    try:
                        # Extract bytes downloaded
                        bytes_part = parts[1].strip().split()[0]
                        bytes_downloaded = int(bytes_part)
                        
                        # Extract duration
                        duration_part = parts[2].strip().rstrip('s')
                        duration_seconds = float(duration_part)
                        
                        # Extract speed and convert to Mbps
                        speed_part = parts[3].strip().split()[0]
                        speed_bytes_per_sec = int(speed_part)
                        speed_mbps = round((speed_bytes_per_sec * 8) / (1024 * 1024), 2)
                        
                        return {
                            'bytes_downloaded': bytes_downloaded,
                            'duration_seconds': duration_seconds,
                            'download_speed_mbps': speed_mbps
                        }
                    except (ValueError, IndexError):
                        logger.error(f"Failed to parse FINAL line: {line}")
                        continue
        
        logger.warning(f"No FINAL line found in log: {log_file_path}")
        return None
        
    except Exception as e:
        logger.error(f"Error reading curl log {log_file_path}: {e}")
        return None

def find_most_recent_log_file():
    """Find the most recent curl progress log file"""
    try:
        log_dir = '/var/log/squid'
        if not os.path.exists(log_dir):
            return None
            
        # Find all curl_progress_*.log files
        log_files = []
        for filename in os.listdir(log_dir):
            if filename.startswith('curl_progress_') and filename.endswith('.log'):
                filepath = os.path.join(log_dir, filename)
                try:
                    mtime = os.path.getmtime(filepath)
                    log_files.append((filepath, mtime))
                except OSError:
                    continue
        
        if not log_files:
            return None
            
        # Return the most recent log file
        log_files.sort(key=lambda x: x[1], reverse=True)
        return log_files[0][0]
        
    except Exception as e:
        logger.error(f"Error finding recent log files: {e}")
        return None

def get_current_prefetch():
    """Get comprehensive pre-fetch status information"""
    # Check for active pre-fetch first
    active_info = get_active_prefetch_info()
    if active_info:
        return active_info
    
    # No active pre-fetch, check for recent completion
    recent_info = get_recent_prefetch_info()
    if recent_info:
        return recent_info
    
    # No recent activity
    return {'status': 'idle'}

def get_active_prefetch_info():
    """Check for currently active pre-fetch process"""
    # First check the PID file and verify process is still running
    pid_file = '/var/log/squid/squid_prefetch.pid'
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = f.read().strip()
            
            if pid:
                # Check if process is still running
                check_cmd = f"kill -0 {pid} 2>/dev/null && echo 'running'"
                if run_command(check_cmd, log_errors=False) == 'running':
                    logger.debug(f"Found active process with PID: {pid}")
                    # Get the command line of the process
                    ps_cmd = f"ps -p {pid} -o args --no-headers"
                    cmd_line = run_command(ps_cmd)
                    
                    if cmd_line and 'curl' in cmd_line:
                        # Extract URL from curl command
                        url_match = re.search(r'https://[^\s]+', cmd_line)
                        if url_match:
                            url = url_match.group(0)
                            
                            # Extract filename from Real-Debrid URL pattern
                            rd_match = re.search(r'https://\d+-\d+\.download\.real-debrid\.com/d/[^/]+/(.+)', url)
                            if rd_match:
                                filename = rd_match.group(1)
                            else:
                                # Fallback: get filename from URL path
                                filename = url.split('/')[-1]
                            
                            # Get file size
                            file_size_mb = get_file_size(url)
                            
                            # Get start time from PID file creation time
                            try:
                                pid_file_stat = os.stat(pid_file)
                                started_at = datetime.fromtimestamp(pid_file_stat.st_mtime).isoformat() + 'Z'
                            except:
                                started_at = None
                            
                            result = {
                                'status': 'active',
                                'filename': filename,
                                'url': url
                            }
                            
                            if file_size_mb is not None:
                                result['file_size_mb'] = file_size_mb
                            if started_at:
                                result['started_at'] = started_at
                                
                            return result
        except Exception as e:
            logger.error(f"Error checking active pre-fetch: {e}")
    
    # Fallback: check for any active curl processes with proxy flag
    curl_cmd = "ps -ef | grep 'curl.*-x.*real-debrid' | grep -v grep"
    curl_output = run_command(curl_cmd, log_errors=False)
    
    if curl_output:
        logger.debug("Found active curl processes via ps command")
        for line in curl_output.split('\n'):
            if 'curl' in line and '-x' in line:
                # Extract URL from curl command
                url_match = re.search(r'https://[^\s]+', line)
                if url_match:
                    url = url_match.group(0)
                    
                    # Extract filename from Real-Debrid URL pattern
                    rd_match = re.search(r'https://\d+-\d+\.download\.real-debrid\.com/d/[^/]+/(.+)', url)
                    if rd_match:
                        filename = rd_match.group(1)
                    else:
                        # Fallback: get filename from URL path
                        filename = url.split('/')[-1]
                    
                    # Get file size
                    file_size_mb = get_file_size(url)
                    
                    result = {
                        'status': 'active',
                        'filename': filename,
                        'url': url
                    }
                    
                    if file_size_mb is not None:
                        result['file_size_mb'] = file_size_mb
                        
                    return result
    
    logger.debug("No active pre-fetch processes found")
    return None

def get_recent_prefetch_info():
    """Check for recent completed or failed pre-fetch"""
    # Find the most recent log file
    recent_log = find_most_recent_log_file()
    if not recent_log:
        return None
    
    try:
        # Check if log file is recent (within last hour)
        log_mtime = os.path.getmtime(recent_log)
        current_time = time.time()
        if current_time - log_mtime > 3600:  # 1 hour
            return None
        
        # Extract filename from log file name
        # Format: curl_progress_YYYYMMDD_HHMMSS_PID.log
        log_filename = os.path.basename(recent_log)
        
        # Try to get URL from lock file if it exists
        url = None
        filename = None
        
        lock_file = '/var/log/squid/squid_prefetch.lock'
        if os.path.exists(lock_file):
            try:
                with open(lock_file, 'r') as f:
                    lock_content = f.read().strip()
                    # Parse lock content: PID:FILENAME:TIMESTAMP
                    lock_data = lock_content.split(':', 2)
                    if len(lock_data) >= 2:
                        filename = lock_data[1]
            except:
                pass
        
        # Parse completion log for statistics
        completion_stats = parse_curl_completion_log(recent_log)
        
        if completion_stats:
            # Successfully completed
            result = {'status': 'completed'}
            
            if filename:
                result['filename'] = filename
            
            # Get file size if we have filename
            if filename and url:
                file_size_mb = get_file_size(url)
                if file_size_mb is not None:
                    result['file_size_mb'] = file_size_mb
            
            # Add start time from log file creation
            try:
                started_at = datetime.fromtimestamp(log_mtime - completion_stats['duration_seconds']).isoformat() + 'Z'
                result['started_at'] = started_at
            except:
                pass
            
            # Add completion stats
            result['bytes_downloaded'] = completion_stats['bytes_downloaded']
            result['download_speed_mbps'] = completion_stats['download_speed_mbps'] 
            result['duration_seconds'] = completion_stats['duration_seconds']
            
            # Add completion time
            try:
                completed_at = datetime.fromtimestamp(log_mtime).isoformat() + 'Z'
                result['completed_at'] = completed_at
            except:
                pass
                
            return result
        else:
            # Failed - log exists but no completion stats
            result = {'status': 'failed'}
            
            if filename:
                result['filename'] = filename
            
            # Add start time from log file creation
            try:
                started_at = datetime.fromtimestamp(log_mtime).isoformat() + 'Z'
                result['started_at'] = started_at
            except:
                pass
                
            return result
            
    except Exception as e:
        logger.error(f"Error checking recent pre-fetch: {e}")
        return None
    
    return None

@app.route('/api/status', methods=['GET'])
def get_squid_status():
    """Get comprehensive Squid cache and prefetch status"""
    # Get cache usage
    command = "sudo du -sm /var/spool/squid | awk '{print $1}'"
    usage_mb = run_command(command)
    
    if usage_mb is None:
        return jsonify({
            'error': 'Failed to retrieve cache usage',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500
    
    try:
        usage_mb = int(usage_mb)
    except ValueError:
        return jsonify({
            'error': 'Invalid cache usage data', 
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500
    
    # Build cache info
    cache_info = {'usage_mb': usage_mb}
    
    configured_size_mb = get_configured_cache_size()
    if configured_size_mb is not None:
        cache_info['configured_size_mb'] = configured_size_mb
        cache_info['usage_percent'] = round((usage_mb / configured_size_mb) * 100, 2) if configured_size_mb > 0 else 0
    
    # Get download info
    download_info = get_current_prefetch()
    
    # Build unified response
    response = {
        'cache': cache_info,
        'download': download_info,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }
    
    return jsonify(response)

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'squid-metrics-api',
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/api/metrics', methods=['GET'])
def list_metrics():
    """List available API endpoints"""
    return jsonify({
        'available_endpoints': [
            {
                'name': 'status',
                'endpoint': '/api/status',
                'description': 'Comprehensive Squid cache and download status information'
            },
            {
                'name': 'health',
                'endpoint': '/api/health', 
                'description': 'API health check'
            }
        ],
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, processes=2, threaded=False)