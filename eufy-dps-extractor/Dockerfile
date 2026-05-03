FROM eclipse-temurin:21-jdk-jammy

LABEL maintainer="eufy-dps-extractor"
LABEL description="Decompiles eufy Clean APK and extracts all Tuya DPS codes"

# -------------------------------------------------------------------------
# System deps
# -------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip python3 python3-pip curl jq file \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------------------------------------------------
# Install jadx (the best Android decompiler, way better than dex2jar)
# -------------------------------------------------------------------------
ARG JADX_VERSION=1.5.1
RUN mkdir -p /opt/jadx && \
    wget -q "https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip" \
         -O /tmp/jadx.zip && \
    unzip -q /tmp/jadx.zip -d /opt/jadx && \
    chmod +x /opt/jadx/bin/jadx /opt/jadx/bin/jadx-gui && \
    ln -s /opt/jadx/bin/jadx /usr/local/bin/jadx && \
    rm /tmp/jadx.zip

# -------------------------------------------------------------------------
# Working directories
# -------------------------------------------------------------------------
RUN mkdir -p /apk /output /work
WORKDIR /work

# -------------------------------------------------------------------------
# Copy extraction scripts
# -------------------------------------------------------------------------
COPY extract.sh /usr/local/bin/extract.sh
COPY deep_scan.py /usr/local/bin/deep_scan.py
RUN chmod +x /usr/local/bin/extract.sh

# -------------------------------------------------------------------------
# Volumes:
#   /apk     - mount your APK file(s) here
#   /output  - results will be written here
# -------------------------------------------------------------------------
VOLUME ["/apk", "/output"]

ENTRYPOINT ["/usr/local/bin/extract.sh"]
