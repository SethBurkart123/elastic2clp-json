import os
import shutil
import subprocess
import sys
import getpass
from pathlib import Path

CLP_JSON_DIR = Path("clp-json-x86_64-v0.7.0")
CLP_JSON_TAR = "clp-json-x86_64-v0.7.0.tar.gz"
CLP_JSON_URL = "https://github.com/y-scope/clp/releases/download/v0.7.0/clp-json-x86_64-v0.7.0.tar.gz"

def is_clp_json_setup():
    return CLP_JSON_DIR.exists() and (CLP_JSON_DIR / "sbin" / "compress.sh").exists()

def run_sudo_command(cmd, password=None):
    """Run a sudo command, prompting for password if needed"""
    if password is None:
        password = getpass.getpass("Enter sudo password: ")
    
    process = subprocess.Popen(
        ["sudo", "-S"] + cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = process.communicate(input=password + "\n")
    
    if process.returncode != 0:
        if "password" in stderr.lower() or "incorrect" in stderr.lower():
            raise subprocess.CalledProcessError(process.returncode, cmd, "Incorrect sudo password")
        raise subprocess.CalledProcessError(process.returncode, cmd, stderr)
    
    return stdout

def setup_clp_json():
    if is_clp_json_setup():
        print("CLP-JSON is already set up.")
        return True
    
    print("Setting up CLP-JSON...")
    password = None
    
    if sys.platform == "linux":
        print("Installing system dependencies (requires sudo)...")
        password = getpass.getpass("Enter sudo password: ")
        
        run_sudo_command(["apt", "update"], password)
        run_sudo_command(["apt", "install", "-y", "wget", "tar"], password)
        
        if subprocess.run(["docker", "--version"], capture_output=True).returncode != 0:
            print("Installing Docker...")
            run_sudo_command(["apt", "install", "-y", "docker.io"], password)
            run_sudo_command(["systemctl", "start", "docker"], password)
            run_sudo_command(["systemctl", "enable", "docker"], password)
    
    print("Downloading CLP-JSON...")
    subprocess.run(["wget", CLP_JSON_URL], check=True)
    print("Extracting CLP-JSON...")
    subprocess.run(["tar", "-xvzf", CLP_JSON_TAR], check=True)
    os.remove(CLP_JSON_TAR)
    
    config_source = Path("clp-config/clp-config.yaml")
    config_dest = CLP_JSON_DIR / "etc" / "clp-config.yaml"
    config_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_source, config_dest)
    
    if sys.platform == "linux":
        if password is None:
            password = getpass.getpass("Enter sudo password for Docker group setup: ")
        print("Configuring Docker group...")
        try:
            run_sudo_command(["groupadd", "docker"], password)
        except subprocess.CalledProcessError:
            pass
        try:
            run_sudo_command(["usermod", "-aG", "docker", os.environ.get("USER", "")], password)
        except subprocess.CalledProcessError:
            pass
        print("Note: You may need to log out and back in for Docker group changes to take effect.")
    
    print("Starting CLP-JSON services...")
    subprocess.run(["sbin/start-clp.sh"], cwd=CLP_JSON_DIR, check=True)
    
    if is_clp_json_setup():
        print("CLP-JSON setup completed successfully!")
        return True
    else:
        print("Error: CLP-JSON setup may have failed. Please check the output above.")
        return False

if __name__ == "__main__":
    sys.exit(0 if setup_clp_json() else 1)
