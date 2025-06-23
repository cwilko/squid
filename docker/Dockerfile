# Multi-stage Dockerfile for Enhanced Squid with Range Forwarding
# Built from https://github.com/cwilko/squid (v5 branch)

# Stage 1: Build Environment
FROM ubuntu:22.04 AS builder

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    autotools-dev \
    automake \
    autoconf \
    libtool \
    pkg-config \
    git \
    libssl-dev \
    libcap-dev \
    libdb-dev \
    libexpat1-dev \
    libgnutls28-dev \
    libkrb5-dev \
    libldap2-dev \
    libltdl-dev \
    libnetfilter-queue-dev \
    libpam0g-dev \
    libsasl2-dev \
    libxml2-dev \
    nettle-dev \
    libecap3-dev \
    libsystemd-dev \
    ed \
    && rm -rf /var/lib/apt/lists/*

# Create build directory
WORKDIR /build

# Clone the enhanced squid repository (v5 branch with range forwarding)
RUN git clone --branch v5 --depth 1 https://github.com/cwilko/squid.git .

# Generate configure script
RUN ./bootstrap.sh

# Configure build with specified options
RUN ./configure \
    --prefix=/usr \
    --localstatedir=/var \
    --libexecdir=/usr/lib/squid \
    --datadir=/usr/share/squid \
    --sysconfdir=/etc/squid \
    --with-default-user=proxy \
    --with-logdir=/var/log/squid \
    --with-pidfile=/var/run/squid.pid \
    --with-openssl \
    --enable-ssl-crtd \
    --enable-icap-client \
    --enable-auth \
    --enable-auth-basic \
    --enable-auth-digest \
    --enable-auth-negotiate \
    --enable-auth-ntlm \
    --enable-removal-policies="lru,heap" \
    --enable-delay-pools \
    --enable-cache-digests \
    --enable-icmp \
    --enable-follow-x-forwarded-for \
    --enable-arp-acl \
    --enable-linux-netfilter \
    --disable-translation \
    --with-large-files \
    --with-filedescriptors=65536 \
    --with-systemd \
    CXXFLAGS="-Wno-error -Wno-deprecated-declarations" \
    CFLAGS="-Wno-error -Wno-deprecated-declarations"

# Build squid
RUN make -j$(nproc)

# Install to temporary directory for packaging
RUN make install DESTDIR=/tmp/squid-install

# Stage 2: Runtime Environment
FROM ubuntu:22.04

LABEL maintainer="cwilko"
LABEL description="Enhanced Squid Proxy with Range Forwarding optimization"
LABEL version="5.10-enhanced"

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies (including Python3 for external store_id scripts)
RUN apt-get update && apt-get install -y \
    libssl3 \
    libcap2 \
    libdb5.3 \
    libexpat1 \
    libgnutls30 \
    libkrb5-3 \
    libldap-2.5-0 \
    libltdl7 \
    libnetfilter-queue1 \
    libpam0g \
    libsasl2-2 \
    libxml2 \
    nettle-bin \
    libecap3 \
    libsystemd0 \
    ca-certificates \
    python3 \
    python3-minimal \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Create proxy user and group (if they don't exist)
RUN if ! getent group proxy >/dev/null; then groupadd -r proxy; fi && \
    if ! getent passwd proxy >/dev/null; then useradd -r -g proxy proxy; fi

# Copy built squid from builder stage (excluding conflicting directories)
COPY --from=builder /tmp/squid-install/usr /usr/
COPY --from=builder /tmp/squid-install/etc /etc/
COPY --from=builder /tmp/squid-install/var/log /var/log/
COPY --from=builder /tmp/squid-install/var/cache /var/cache/

# Copy MIME configuration from source (both to /etc/squid and backup location)
COPY src/mime.conf.default /etc/squid/mime.conf
RUN mkdir -p /usr/share/squid/conf-defaults
COPY src/mime.conf.default /usr/share/squid/conf-defaults/mime.conf

# Create necessary directories and set permissions (excluding ssl_db which gets created by security_file_certgen)
RUN mkdir -p /var/cache/squid /var/log/squid /var/spool/squid /var/run /etc/squid /var/lib/squid \
    && chown -R proxy:proxy /var/cache/squid /var/log/squid /var/spool/squid /var/run /var/lib/squid /etc/squid \
    && chmod 755 /var/cache/squid /var/log/squid /var/spool/squid /var/run

# Fix helper binary permissions for ICMP and SSL functionality
RUN if [ -f /usr/lib/squid/pinger ]; then \
    chown root:proxy /usr/lib/squid/pinger && \
    chmod 4755 /usr/lib/squid/pinger; \
fi && \
if [ -f /usr/lib/squid/security_file_certgen ]; then \
    chown root:proxy /usr/lib/squid/security_file_certgen && \
    chmod 4755 /usr/lib/squid/security_file_certgen; \
fi

# Copy entrypoint script
COPY docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create minimal squid.conf if none exists
RUN if [ ! -f /etc/squid/squid.conf ]; then \
    echo "# Enhanced Squid with Range Forwarding" > /etc/squid/squid.conf && \
    echo "http_port 3128" >> /etc/squid/squid.conf && \
    echo "acl localnet src 10.0.0.0/8" >> /etc/squid/squid.conf && \
    echo "acl localnet src 172.16.0.0/12" >> /etc/squid/squid.conf && \
    echo "acl localnet src 192.168.0.0/16" >> /etc/squid/squid.conf && \
    echo "acl SSL_ports port 443" >> /etc/squid/squid.conf && \
    echo "acl Safe_ports port 80" >> /etc/squid/squid.conf && \
    echo "acl Safe_ports port 443" >> /etc/squid/squid.conf && \
    echo "acl CONNECT method CONNECT" >> /etc/squid/squid.conf && \
    echo "http_access deny !Safe_ports" >> /etc/squid/squid.conf && \
    echo "http_access deny CONNECT !SSL_ports" >> /etc/squid/squid.conf && \
    echo "http_access allow localhost manager" >> /etc/squid/squid.conf && \
    echo "http_access deny manager" >> /etc/squid/squid.conf && \
    echo "http_access allow localnet" >> /etc/squid/squid.conf && \
    echo "http_access allow localhost" >> /etc/squid/squid.conf && \
    echo "http_access deny all" >> /etc/squid/squid.conf && \
    echo "" >> /etc/squid/squid.conf && \
    echo "# Enhanced Range Forwarding Feature" >> /etc/squid/squid.conf && \
    echo "range_forward_on_cache_miss on" >> /etc/squid/squid.conf && \
    echo "" >> /etc/squid/squid.conf && \
    echo "cache_dir ufs /var/cache/squid 1000 16 256" >> /etc/squid/squid.conf && \
    echo "maximum_object_size 1 GB" >> /etc/squid/squid.conf && \
    echo "cache_mem 256 MB" >> /etc/squid/squid.conf && \
    chown proxy:proxy /etc/squid/squid.conf; \
fi

# Expose default squid port
EXPOSE 3128

# Environment variables for configuration
ENV SQUID_CONFIG_FILE=/etc/squid/squid.conf
ENV SQUID_CACHE_DIR=/var/cache/squid
ENV SQUID_LOG_DIR=/var/log/squid
ENV RANGE_FORWARD=on

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD /usr/bin/squid -k check || exit 1

# Set entrypoint
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/usr/sbin/squid", "-NYCd", "1"]