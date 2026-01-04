# If using proxmox make sure to change cpu type to host!

# Install required tools
sudo apt update
sudo apt install wget tar

# somehow setup docker here

# Download https://github.com/y-scope/clp/releases/download/v0.7.0/clp-json-x86_64-v0.7.0.tar.gz
wget https://github.com/y-scope/clp/releases/download/v0.7.0/clp-json-x86_64-v0.7.0.tar.gz
# unzip 
tar -xvzf clp-json-x86_64-v0.7.0.tar.gz
# cleanup files
rm clp-json-x86_64-v0.7.0.tar.gz

# Copy config
cp clp-config/clp-config.yaml clp-json-x86_64-v0.7.0/etc/clp-config.yaml

# Allow docker to run without sudo
sudo groupadd docker
sudo usermod -aG docker $USER
newgrp docker
# verify it works (optional)
docker ps

# start clp-json
cd clp-json-x86_64-v0.7.0
sbin/start-clp.sh
