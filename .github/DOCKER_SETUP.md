# GitHub Actions Docker Setup Guide

This guide explains how to set up automated Docker image building and publishing for your enhanced Squid proxy.

## 🔐 Prerequisites

Before the GitHub Actions can push to Docker Hub, you need to set up authentication:

### 1. Create Docker Hub Access Token

1. Go to [Docker Hub](https://hub.docker.com/) and sign in
2. Click on your profile → **Account Settings**
3. Go to **Security** → **New Access Token**
4. Create a token with **Read, Write, Delete** permissions
5. Copy the token (you won't see it again!)

### 2. Configure GitHub Secrets

In your GitHub repository, add these secrets:

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Add **New repository secret**:
   - `DOCKERHUB_USERNAME`: Your Docker Hub username
   - `DOCKERHUB_TOKEN`: The access token you created above

## 🚀 Workflows Overview

### `docker-build.yml` - Main Build Pipeline

**Triggers:**
- Push to `v5` or `main` branches
- New tags (for releases)
- Changes to `src/**` or `docker/**` files
- Manual trigger via GitHub UI

**Features:**
- Multi-architecture builds (AMD64 + ARM64)
- Automatic testing of built images
- Smart tagging based on branch/tag
- Docker layer caching for faster builds
- Automatic push to Docker Hub

**Image Tags Generated:**
- `latest` (for main branch)
- `v5` (for v5 branch)
- `range-forwarding` (feature tag)
- `v1.0`, `v1.0.1` etc. (for version tags)
- Branch-specific tags

### `docker-security-scan.yml` - Security Scanning

**Triggers:**
- Push to main branches
- Weekly scheduled scans
- Manual trigger

**Features:**
- Trivy vulnerability scanning
- Docker Scout CVE detection
- Security configuration testing
- Results uploaded to GitHub Security tab

## 📦 Usage Examples

### Automatic Builds

```bash
# Triggered automatically on push to v5 branch
git push origin v5

# Create a release tag to trigger versioned build
git tag v1.0.0
git push origin v1.0.0
```

### Manual Builds

1. Go to **Actions** tab in your GitHub repo
2. Select **Build and Push Docker Image**
3. Click **Run workflow**
4. Choose branch and options

### Using Built Images

```bash
# Latest development build (v5 branch)
docker pull cwilko/squid:v5

# Latest stable (main branch)
docker pull cwilko/squid:latest

# Specific version
docker pull cwilko/squid:v1.0.0

# Feature-specific tag
docker pull cwilko/squid:range-forwarding
```

## 🔧 Configuration

### Customizing Build Triggers

Edit `.github/workflows/docker-build.yml`:

```yaml
on:
  push:
    branches:
      - v5          # Add your branches here
      - main
      - develop     # Example: add develop branch
```

### Changing Image Name

Update the `IMAGE_NAME` environment variable:

```yaml
env:
  IMAGE_NAME: your-username/your-squid
```

### Platform Support

Current platforms: `linux/amd64,linux/arm64`

To add more platforms, edit the `platforms` field:

```yaml
platforms: linux/amd64,linux/arm64,linux/arm/v7
```

## 📊 Monitoring Builds

### Build Status

- Check the **Actions** tab for build status
- Green checkmark = successful build and push
- Red X = build failed (check logs)

### Docker Hub

- Visit your [Docker Hub repository](https://hub.docker.com/r/cwilko/squid)
- Check **Tags** tab for available images
- View **Activity** for pull statistics

### Security Scans

- Go to **Security** tab in GitHub repo
- View **Code scanning alerts** for vulnerabilities
- Check **Dependabot alerts** for dependency issues

## 🛠 Troubleshooting

### Common Issues

**Build Fails with "Permission Denied"**
- Check DOCKERHUB_USERNAME and DOCKERHUB_TOKEN secrets
- Verify Docker Hub token has write permissions

**Multi-arch Build Fails**
- Some dependencies may not support all architectures
- Consider removing problematic platforms temporarily

**Large Build Times**
- Builds include full Squid compilation (~20-30 minutes)
- Layer caching reduces subsequent build times
- Consider using self-hosted runners for faster builds

**Security Scan Failures**
- Review vulnerability reports in Security tab
- Update base image versions in Dockerfile
- Consider using distroless or alpine base images

### Debugging Builds

1. **Check build logs** in Actions tab
2. **Test locally** before pushing:
   ```bash
   cd docker
   docker build -t test-squid .
   docker run --rm test-squid squid -k parse
   ```

3. **Enable debug mode** by adding to workflow:
   ```yaml
   env:
     ACTIONS_RUNNER_DEBUG: true
   ```

## 🎯 Advanced Configuration

### Custom Build Args

Add build arguments to Dockerfile and workflow:

```dockerfile
ARG SQUID_VERSION=5.10
ARG ENABLE_SSL=yes
```

```yaml
build-args: |
  SQUID_VERSION=5.10
  ENABLE_SSL=yes
```

### Private Registry

To use a private registry instead of Docker Hub:

```yaml
env:
  REGISTRY: your-registry.com
  IMAGE_NAME: your-namespace/squid
```

### Release Automation

The workflow automatically creates release notes for tagged versions. Customize in the "Generate release notes" step.

## 🚀 Next Steps

1. **Set up secrets** in GitHub repository settings
2. **Push changes** to trigger first build
3. **Monitor build** in Actions tab
4. **Test image** once build completes:
   ```bash
   docker run -d -p 3128:3128 cwilko/squid:latest
   ```

5. **Create release** by tagging:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

Your enhanced Squid proxy will now be automatically built and published to Docker Hub! 🎉