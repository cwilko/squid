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
import urllib3

# Disable SSL warnings since we intentionally bypass SSL verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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


def get_download_progress_from_logs(pid):
    """Try to get download progress and file size from active wget log file"""
    try:
        log_dir = '/var/log/squid'
        if not os.path.exists(log_dir):
            return None
            
        # Look for log file with matching PID or recent log file for this process
        log_files = []
        for filename in os.listdir(log_dir):
            if filename.startswith('wget_progress_') and filename.endswith('.log'):
                log_path = os.path.join(log_dir, filename)
                try:
                    mtime = os.path.getmtime(log_path)
                    log_files.append((log_path, mtime, filename))
                except OSError:
                    continue
        
        # Sort by modification time, newest first
        log_files.sort(key=lambda x: x[1], reverse=True)
        
        # Look for exact PID match first, then fall back to most recent
        target_log = None
        for log_path, mtime, filename in log_files:
            if filename.endswith(f'_{pid}.log'):
                target_log = log_path
                break
        
        # If no exact match, use the most recent log file (within last 5 minutes)
        if not target_log and log_files:
            recent_log_path, recent_mtime, recent_filename = log_files[0]
            current_time = time.time()
            if current_time - recent_mtime < 300:  # 5 minutes
                target_log = recent_log_path
        
        if target_log:
            with open(target_log, 'r') as f:
                content = f.read()
                
            
            result = {'file_size_mb': None, 'downloaded_mb': None, 'progress_percent': None}
            
            # Parse Content-Length from server response headers
            content_length_match = re.search(r'Content-Length:\s*(\d+)', content, re.IGNORECASE)
            if content_length_match:
                try:
                    size_bytes = int(content_length_match.group(1))
                    result['file_size_mb'] = round(size_bytes / (1024 * 1024), 2)
                except ValueError:
                    pass
            
            # Parse current progress from wget dot output
            # Format examples:
            # "     0K ........ ........ ........ ........ 32768K"
            # " 32768K ........ ........ ........ ........ 65536K"
            # Look for the last line with progress info
            lines = content.split('\n')
            last_progress_kb = 0
            
            
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                    
                # Match the actual wget progress format:
                # "3833856K ........ ........ ........ ........ 18% 38.1M 11m34s"
                kb_match = re.search(r'^(\d+)K\s+[.\s]+', line)
                if kb_match:
                    try:
                        last_progress_kb = int(kb_match.group(1))
                        break
                    except ValueError:
                        continue
            
            
            if last_progress_kb > 0:
                result['downloaded_mb'] = round(last_progress_kb / 1024, 2)
                
                # Calculate progress percentage if we have file size
                if result['file_size_mb'] and result['file_size_mb'] > 0:
                    result['progress_percent'] = round((result['downloaded_mb'] / result['file_size_mb']) * 100, 1)
            
            return result
        
        return None
        
    except Exception as e:
        logger.error(f"Error reading wget log for PID {pid}: {e}")
        return None

def get_file_size_from_logs(pid):
    """Try to get file size from active wget log file (backward compatibility)"""
    progress_info = get_download_progress_from_logs(pid)
    return progress_info['file_size_mb'] if progress_info else None

def parse_wget_log(log_file_path):
    """Parse wget log to extract completion status and file size"""
    try:
        with open(log_file_path, 'r') as f:
            content = f.read()
            
        result = {'status': 'unknown', 'file_size_mb': None}
        
        # Parse Content-Length from server response headers
        content_length_match = re.search(r'Content-Length:\s*(\d+)', content, re.IGNORECASE)
        if content_length_match:
            try:
                size_bytes = int(content_length_match.group(1))
                result['file_size_mb'] = round(size_bytes / (1024 * 1024), 2)
            except ValueError:
                pass
        
        # Check for wget success indicators
        # wget typically shows "saved" when successful
        if 'saved [' in content.lower() or 'downloaded:' in content.lower():
            result['status'] = 'completed'
            return result
        
        # Check for wget error indicators
        error_indicators = [
            'error', 'failed', 'unable to resolve',
            'connection refused', 'timeout', 'not found'
        ]
        
        content_lower = content.lower()
        for indicator in error_indicators:
            if indicator in content_lower:
                result['status'] = 'failed'
                return result
        
        # If log exists but no clear success/failure indicators, 
        # it might still be running or incomplete
        result['status'] = 'unknown'
        return result
        
    except Exception as e:
        logger.error(f"Error reading wget log {log_file_path}: {e}")
        return {'status': 'failed', 'file_size_mb': None}

def extract_start_time_from_log_filename(log_filename):
    """Extract start timestamp from wget log filename format: wget_progress_{timestamp}_{pid}.log"""
    try:
        # Extract timestamp from filename
        # Format: wget_progress_1751365237_121.log
        parts = log_filename.split('_')
        if len(parts) >= 3 and parts[0] == 'wget' and parts[1] == 'progress':
            timestamp_str = parts[2]
            try:
                timestamp = int(timestamp_str)
                return datetime.fromtimestamp(timestamp).isoformat() + 'Z'
            except (ValueError, OSError):
                logger.debug(f"Invalid timestamp in filename: {timestamp_str}")
                return None
        else:
            logger.debug(f"Filename doesn't match expected format: {log_filename}")
            return None
    except Exception as e:
        logger.error(f"Error extracting timestamp from filename {log_filename}: {e}")
        return None

def find_most_recent_log_file():
    """Find the most recent wget progress log file"""
    try:
        log_dir = '/var/log/squid'
        if not os.path.exists(log_dir):
            return None
            
        # Find all wget_progress_*.log files
        log_files = []
        for filename in os.listdir(log_dir):
            if filename.startswith('wget_progress_') and filename.endswith('.log'):
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
                    # Check if process is actually running (not zombie/defunct)
                    status_cmd = f"ps -p {pid} -o stat --no-headers"
                    status = run_command(status_cmd, log_errors=False)
                    
                    if status and 'Z' in status:
                        logger.debug(f"Process {pid} is zombie/defunct, treating as failed")
                        # Get process info from ps to extract details for failed status
                        ps_cmd = f"ps -p {pid} -o args --no-headers"
                        cmd_line = run_command(ps_cmd, log_errors=False)
                        
                        if cmd_line and 'wget' in cmd_line:
                            # Extract URL and filename from zombie wget command
                            url_match = re.search(r'https://[^\s]+', cmd_line)
                            if url_match:
                                url = url_match.group(0)
                                
                                # Extract filename from Real-Debrid URL pattern
                                rd_match = re.search(r'https://\d+-\d+\.download\.real-debrid\.com/d/[^/]+/(.+)', url)
                                if rd_match:
                                    filename = rd_match.group(1)
                                else:
                                    filename = url.split('/')[-1]
                                
                                # Try to get progress info from wget log first, then fallback to HEAD request  
                                progress_info = get_download_progress_from_logs(pid)
                                if progress_info and progress_info['file_size_mb'] is not None:
                                    file_size_mb = progress_info['file_size_mb']
                                    downloaded_mb = progress_info['downloaded_mb'] 
                                    progress_percent = progress_info['progress_percent']
                                else:
                                    file_size_mb = get_file_size(url)
                                    downloaded_mb = None
                                    progress_percent = None
                                
                                # Get start time from PID file creation time
                                try:
                                    pid_file_stat = os.stat(pid_file)
                                    started_at = datetime.fromtimestamp(pid_file_stat.st_mtime).isoformat() + 'Z'
                                except:
                                    started_at = None
                                
                                result = {
                                    'status': 'failed',
                                    'filename': filename,
                                    'url': url
                                }
                                
                                if file_size_mb is not None:
                                    result['file_size_mb'] = file_size_mb
                                if downloaded_mb is not None:
                                    result['downloaded_mb'] = downloaded_mb
                                if progress_percent is not None:
                                    result['progress_percent'] = progress_percent
                                if started_at:
                                    result['started_at'] = started_at
                                    
                                return result
                    
                    # Get the command line of the process
                    ps_cmd = f"ps -p {pid} -o args --no-headers"
                    cmd_line = run_command(ps_cmd)
                    
                    if cmd_line and 'wget' in cmd_line:
                        # Extract URL from wget command
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
                            
                            # Try to get progress info from wget log first, then fallback to HEAD request
                            progress_info = get_download_progress_from_logs(pid)
                            if progress_info and progress_info['file_size_mb'] is not None:
                                file_size_mb = progress_info['file_size_mb']
                                downloaded_mb = progress_info['downloaded_mb'] 
                                progress_percent = progress_info['progress_percent']
                            else:
                                file_size_mb = get_file_size(url)
                                downloaded_mb = None
                                progress_percent = None
                            
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
                            if downloaded_mb is not None:
                                result['downloaded_mb'] = downloaded_mb
                            if progress_percent is not None:
                                result['progress_percent'] = progress_percent
                            if started_at:
                                result['started_at'] = started_at
                                
                            return result
        except Exception as e:
            logger.error(f"Error checking active pre-fetch: {e}")
    
    # Fallback: check for any active wget processes with proxy flag (exclude zombies)
    wget_cmd = "ps -ef | grep 'wget.*--proxy.*real-debrid' | grep -v grep | grep -v defunct"
    wget_output = run_command(wget_cmd, log_errors=False)
    
    if wget_output:
        for line in wget_output.split('\n'):
            if 'wget' in line and '--proxy' in line:
                # Extract URL from wget command
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
                    
                    # Get file size (this case doesn't have PID, so just use HEAD request)
                    file_size_mb = get_file_size(url)
                    
                    result = {
                        'status': 'active',
                        'filename': filename,
                        'url': url
                    }
                    
                    if file_size_mb is not None:
                        result['file_size_mb'] = file_size_mb
                        
                    return result
    
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
        # Format: wget_progress_{timestamp}_{pid}.log
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
        
        # Parse wget log for completion status and file size
        wget_result = parse_wget_log(recent_log)
        
        if wget_result['status'] == 'completed':
            # Successfully completed
            result = {'status': 'completed'}
            
            if filename:
                result['filename'] = filename
            
            # Use file size from wget log if available, otherwise try HEAD request as fallback
            if wget_result['file_size_mb'] is not None:
                result['file_size_mb'] = wget_result['file_size_mb']
            elif filename and url:
                file_size_mb = get_file_size(url)
                if file_size_mb is not None:
                    result['file_size_mb'] = file_size_mb
            
            # Add start time from log filename
            started_at = extract_start_time_from_log_filename(log_filename)
            if started_at:
                result['started_at'] = started_at
            
            # Add completion time (use file modification time)
            try:
                completed_at = datetime.fromtimestamp(log_mtime).isoformat() + 'Z'
                result['completed_at'] = completed_at
            except:
                pass
                
            return result
        else:
            # Failed or unknown - log exists but wget didn't complete successfully
            result = {'status': wget_result['status'] if wget_result['status'] in ['failed', 'unknown'] else 'failed'}
            
            if filename:
                result['filename'] = filename
            
            # Include file size from wget log if available, even for failed downloads
            if wget_result['file_size_mb'] is not None:
                result['file_size_mb'] = wget_result['file_size_mb']
            
            # Add start time from log filename
            started_at = extract_start_time_from_log_filename(log_filename)
            if started_at:
                result['started_at'] = started_at
                
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