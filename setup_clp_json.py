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
        
        if shutil.which("docker") is None:
            print("Installing Docker using official repository...")
            run_sudo_command(["apt", "install", "-y", "ca-certificates", "curl"], password)
            run_sudo_command(["install", "-m", "0755", "-d", "/etc/apt/keyrings"], password)
            
            curl_process = subprocess.Popen(
                ["curl", "-fsSL", "https://download.docker.com/linux/ubuntu/gpg"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            gpg_data, curl_stderr = curl_process.communicate()
            if curl_process.returncode != 0:
                raise subprocess.CalledProcessError(curl_process.returncode, ["curl"], curl_stderr.decode())
            
            tee_process = subprocess.Popen(
                ["sudo", "-S", "tee", "/etc/apt/keyrings/docker.asc"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            tee_stdout, tee_stderr = tee_process.communicate(input=(password + "\n").encode() + gpg_data)
            if tee_process.returncode != 0:
                raise subprocess.CalledProcessError(tee_process.returncode, ["tee"], tee_stderr.decode())
            
            run_sudo_command(["chmod", "a+r", "/etc/apt/keyrings/docker.asc"], password)
            
            codename_result = subprocess.run(
                ["bash", "-c", '. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}"'],
                capture_output=True,
                text=True,
                check=True
            )
            codename = codename_result.stdout.strip()
            
            sources_content = f"""Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: {codename}
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
"""
            
            tee_process = subprocess.Popen(
                ["sudo", "-S", "tee", "/etc/apt/sources.list.d/docker.sources"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            tee_stdout, tee_stderr = tee_process.communicate(input=password + "\n" + sources_content)
            if tee_process.returncode != 0:
                raise subprocess.CalledProcessError(tee_process.returncode, ["tee"], tee_stderr)
            
            run_sudo_command(["apt", "update"], password)
            run_sudo_command(["apt", "install", "-y", "docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"], password)
            
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
