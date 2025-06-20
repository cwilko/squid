# Enhanced Squid Proxy with Range Forwarding

This Docker image contains a custom build of Squid proxy with **range forwarding optimization** for large file downloads. This enhancement is particularly useful for scenarios where multiple clients request different ranges of the same large file.

## 🚀 Features

- **Range Forwarding Optimization**: Automatically forwards out-of-range requests to upstream servers instead of waiting for sequential downloads
- **Collapsed Forwarding**: Multiple clients downloading the same file share bandwidth efficiently  
- **Large File Support**: Optimized for handling large file downloads (videos, archives, etc.)
- **Production Ready**: Built with comprehensive feature set and security configurations

## 📋 Quick Start

### Basic Usage

```bash
# Run with default configuration (range forwarding enabled)
docker run -d -p 3128:3128 --name squid-enhanced cwilko/squid-enhanced

# Run with custom configuration file
docker run -d -p 3128:3128 \
  -v /path/to/your/squid.conf:/etc/squid/squid.conf \
  --name squid-enhanced cwilko/squid-enhanced
```

### With Persistent Cache

```bash
# Create cache volume for persistence
docker volume create squid-cache

# Run with persistent cache
docker run -d -p 3128:3128 \
  -v squid-cache:/var/cache/squid \
  --name squid-enhanced cwilko/squid-enhanced
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RANGE_FORWARD` | `on` | Enable/disable range forwarding (`on`/`off`) |
| `SQUID_CONFIG_FILE` | `/etc/squid/squid.conf` | Path to configuration file |
| `SQUID_CACHE_DIR` | `/var/cache/squid` | Cache directory path |
| `SQUID_LOG_DIR` | `/var/log/squid` | Log directory path |

Example with environment variables:
```bash
docker run -d -p 3128:3128 \
  -e RANGE_FORWARD=on \
  --name squid-enhanced cwilko/squid-enhanced
```

## 🔧 Configuration

### Range Forwarding Feature

The range forwarding feature is automatically enabled by default. To configure it manually, add this to your `squid.conf`:

```
# Enable range forwarding optimization
range_forward_on_cache_miss on
```

### Sample Configuration

The container includes a basic configuration suitable for most use cases:

- HTTP proxy on port 3128
- Access allowed for local networks (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
- 1GB cache directory with 256MB memory cache
- Range forwarding enabled
- Maximum object size: 1GB (suitable for large files)

### Custom Configuration

To use your own configuration:

1. Create your `squid.conf` file
2. Mount it into the container:
```bash
docker run -d -p 3128:3128 \
  -v /path/to/your/squid.conf:/etc/squid/squid.conf \
  cwilko/squid-enhanced
```

## 📊 Use Cases

### Scenario 1: Video Streaming
- Client A starts downloading large video file (10GB)
- Client B requests specific range (e.g., seeking to middle of video)
- **Without range forwarding**: Client B waits for sequential download
- **With range forwarding**: Client B gets immediate response from upstream

### Scenario 2: Software Downloads
- Multiple clients downloading the same software package
- Some clients need full file, others need specific ranges
- Range forwarding optimizes bandwidth usage and response times

### Scenario 3: Content Delivery
- Large file being downloaded by one client
- Additional clients request different byte ranges
- Range forwarding prevents duplicate downloads and reduces latency

## 🐳 Building from Source

To build your own image from the enhanced source:

```bash
# Clone this repository
git clone https://github.com/cwilko/squid.git
cd squid/docker

# Build the image
docker build -t my-squid-enhanced .

# Run your custom build
docker run -d -p 3128:3128 my-squid-enhanced
```

## 📝 Logs and Monitoring

### Viewing Logs
```bash
# View squid access logs
docker exec squid-enhanced tail -f /var/log/squid/access.log

# View squid cache logs  
docker exec squid-enhanced tail -f /var/log/squid/cache.log

# View container logs
docker logs -f squid-enhanced
```

### Health Check
The container includes a health check that verifies Squid is running:
```bash
# Check container health
docker inspect squid-enhanced | grep -A 5 Health
```

## 🔍 Troubleshooting

### Configuration Issues
```bash
# Test configuration syntax
docker exec squid-enhanced squid -k parse

# Or use the built-in config check
docker run --rm -v /path/to/squid.conf:/etc/squid/squid.conf \
  cwilko/squid-enhanced config-check
```

### Cache Initialization
```bash
# Manually initialize cache (if needed)
docker exec squid-enhanced squid -z
```

### Debug Range Forwarding
Enable debug logging by adding to your `squid.conf`:
```
debug_options ALL,1 88,3
```

Then monitor logs for range forwarding activity:
```bash
docker exec squid-enhanced grep "Range request analysis" /var/log/squid/cache.log
```

## 🚀 Performance Tips

1. **Memory**: Allocate sufficient memory for cache_mem (recommended: 25% of available RAM)
2. **Storage**: Use fast storage for cache directory (SSD recommended)
3. **File Descriptors**: Default 65536 should be sufficient for most use cases
4. **Network**: Ensure adequate bandwidth between proxy and upstream servers

## 📄 License

This enhanced version maintains the original Squid GPLv2+ license. The range forwarding enhancement is provided under the same license terms.

## 🤝 Contributing

This image is built from the enhanced Squid source at: https://github.com/cwilko/squid

For issues related to the range forwarding feature, please open issues in the source repository.

## 📈 Version Information

- **Base Squid Version**: 5.10-VCS
- **Enhancement**: Range Forwarding Optimization
- **Build Configuration**: Production-ready with SSL, authentication, and caching optimizations
- **Container Base**: Ubuntu 22.04 LTS