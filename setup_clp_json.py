import os
import shutil
import subprocess
import sys
from pathlib import Path

CLP_JSON_DIR = Path("clp-json-x86_64-v0.7.0")
CLP_JSON_TAR = "clp-json-x86_64-v0.7.0.tar.gz"
CLP_JSON_URL = "https://github.com/y-scope/clp/releases/download/v0.7.0/clp-json-x86_64-v0.7.0.tar.gz"

def is_clp_json_setup():
    return CLP_JSON_DIR.exists() and (CLP_JSON_DIR / "sbin" / "compress.sh").exists()

def setup_clp_json():
    if is_clp_json_setup():
        return True
    
    if sys.platform == "linux":
        subprocess.run(["sudo", "apt", "update"], check=True)
        subprocess.run(["sudo", "apt", "install", "-y", "wget", "tar"], check=True)
        
        docker_check = subprocess.run(["docker", "--version"], capture_output=True)
        if docker_check.returncode != 0:
            subprocess.run(["sudo", "apt", "install", "-y", "docker.io"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "docker"], check=True)
            subprocess.run(["sudo", "systemctl", "enable", "docker"], check=True)
    
    subprocess.run(["wget", CLP_JSON_URL], check=True)
    subprocess.run(["tar", "-xvzf", CLP_JSON_TAR], check=True)
    os.remove(CLP_JSON_TAR)
    
    config_source = Path("clp-config/clp-config.yaml")
    config_dest = CLP_JSON_DIR / "etc" / "clp-config.yaml"
    config_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_source, config_dest)
    
    if sys.platform == "linux":
        subprocess.run(["sudo", "groupadd", "docker"], check=False)
        subprocess.run(["sudo", "usermod", "-aG", "docker", os.environ.get("USER", "")], check=True)
    
    subprocess.run(["sbin/start-clp.sh"], cwd=CLP_JSON_DIR, check=True)
    
    return is_clp_json_setup()

if __name__ == "__main__":
    sys.exit(0 if setup_clp_json() else 1)
