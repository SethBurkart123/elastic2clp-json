#!/bin/bash

set -e

SERVICE_NAME="elastic2clp-json.service"
SERVICE_FILE="elastic2clp-json.service"
SYSTEMD_DIR="/etc/systemd/system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$EUID" -eq 0 ] && [ -n "$SUDO_USER" ]; then
    CURRENT_USER="$SUDO_USER"
else
    CURRENT_USER=$(whoami)
fi
CURRENT_DIR="$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  Elastic2CLP-JSON Service Manager${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
}

print_menu() {
    echo -e "${GREEN}Select an option:${NC}"
    echo "  1) Setup/Install service"
    echo "  2) Reload service (after config changes)"
    echo "  3) Start service"
    echo "  4) Stop service"
    echo "  5) Restart service"
    echo "  6) Show service status"
    echo "  7) View service logs"
    echo "  8) Uninstall service"
    echo "  9) Exit"
    echo
    read -p "Enter your choice [1-9]: " choice
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}Error: This operation requires root privileges.${NC}"
        echo "Please run with: sudo $0"
        exit 1
    fi
}

check_service_file() {
    if [ ! -f "$SCRIPT_DIR/$SERVICE_FILE" ]; then
        echo -e "${RED}Error: Service file '$SERVICE_FILE' not found in $SCRIPT_DIR${NC}"
        exit 1
    fi
}

setup_service() {
    check_root
    check_service_file
    
    echo -e "${YELLOW}Setting up systemd service...${NC}"
    echo
    
    read -p "Enter username to run service [$CURRENT_USER]: " service_user
    service_user=${service_user:-$CURRENT_USER}
    
    read -p "Enter working directory [$CURRENT_DIR]: " work_dir
    work_dir=${work_dir:-$CURRENT_DIR}
    
    if ! id "$service_user" &>/dev/null; then
        echo -e "${RED}Error: User '$service_user' does not exist${NC}"
        exit 1
    fi
    
    if [ ! -d "$work_dir" ]; then
        echo -e "${RED}Error: Directory '$work_dir' does not exist${NC}"
        exit 1
    fi
    
    user_home=$(getent passwd "$service_user" | cut -d: -f6)
    if [ -f "$user_home/.local/bin/uv" ]; then
        uv_path="$user_home/.local/bin/uv"
    elif command -v uv >/dev/null 2>&1; then
        uv_path=$(command -v uv)
    else
        uv_path="uv"
    fi
    home_local_bin="$user_home/.local/bin"
    
    temp_service=$(mktemp)
    sed "s|YOUR_USERNAME|$service_user|g; s|/path/to/elastic2log|$work_dir|g; s|UV_PATH|$uv_path|g; s|HOME_LOCAL_BIN|$home_local_bin|g" \
        "$SCRIPT_DIR/$SERVICE_FILE" > "$temp_service"
    
    cp "$temp_service" "$SYSTEMD_DIR/$SERVICE_NAME"
    rm "$temp_service"
    systemctl daemon-reload
    
    echo -e "${GREEN}Service file installed to $SYSTEMD_DIR/$SERVICE_NAME${NC}"
    echo
    
    read -p "Enable service to start on boot? [y/N]: " enable_choice
    if [[ "$enable_choice" =~ ^[Yy]$ ]]; then
        systemctl enable "$SERVICE_NAME"
        echo -e "${GREEN}Service enabled to start on boot${NC}"
    fi
    
    read -p "Start service now? [y/N]: " start_choice
    if [[ "$start_choice" =~ ^[Yy]$ ]]; then
        systemctl start "$SERVICE_NAME"
        echo -e "${GREEN}Service started${NC}"
        sleep 1
        systemctl status "$SERVICE_NAME" --no-pager
    fi
}

reload_service() {
    check_root
    check_service_file
    
    echo -e "${YELLOW}Reloading service...${NC}"
    
    if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME" ]; then
        echo -e "${RED}Error: Service is not installed. Please install it first.${NC}"
        exit 1
    fi
    
    current_user=$(grep "^User=" "$SYSTEMD_DIR/$SERVICE_NAME" | cut -d'=' -f2)
    current_dir=$(grep "^WorkingDirectory=" "$SYSTEMD_DIR/$SERVICE_NAME" | cut -d'=' -f2)
    user_home=$(getent passwd "$current_user" | cut -d: -f6)
    if [ -f "$user_home/.local/bin/uv" ]; then
        uv_path="$user_home/.local/bin/uv"
    elif command -v uv >/dev/null 2>&1; then
        uv_path=$(command -v uv)
    else
        uv_path="uv"
    fi
    home_local_bin="$user_home/.local/bin"
    
    temp_service=$(mktemp)
    sed "s|YOUR_USERNAME|$current_user|g; s|/path/to/elastic2log|$current_dir|g; s|UV_PATH|$uv_path|g; s|HOME_LOCAL_BIN|$home_local_bin|g" \
        "$SCRIPT_DIR/$SERVICE_FILE" > "$temp_service"
    
    cp "$temp_service" "$SYSTEMD_DIR/$SERVICE_NAME"
    rm "$temp_service"
    systemctl daemon-reload
    systemctl restart "$SERVICE_NAME"
    
    echo -e "${GREEN}Service reloaded and restarted${NC}"
    sleep 1
    systemctl status "$SERVICE_NAME" --no-pager
}

start_service() {
    check_root
    
    if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME" ]; then
        echo -e "${RED}Error: Service is not installed. Please install it first.${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Starting service...${NC}"
    systemctl start "$SERVICE_NAME"
    sleep 1
    systemctl status "$SERVICE_NAME" --no-pager
}

stop_service() {
    check_root
    
    if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME" ]; then
        echo -e "${RED}Error: Service is not installed. Please install it first.${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Stopping service...${NC}"
    systemctl stop "$SERVICE_NAME"
    echo -e "${GREEN}Service stopped${NC}"
}

restart_service() {
    check_root
    
    if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME" ]; then
        echo -e "${RED}Error: Service is not installed. Please install it first.${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Restarting service...${NC}"
    systemctl restart "$SERVICE_NAME"
    sleep 1
    systemctl status "$SERVICE_NAME" --no-pager
}

show_status() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}Note: Some information may require root privileges${NC}"
        echo
    fi
    
    if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME" ]; then
        echo -e "${RED}Service is not installed${NC}"
        exit 0
    fi
    
    echo -e "${BLUE}Service Status:${NC}"
    systemctl status "$SERVICE_NAME" --no-pager || true
    echo
    
    echo -e "${BLUE}Service Configuration:${NC}"
    if [ "$EUID" -eq 0 ]; then
        echo "  User: $(grep "^User=" "$SYSTEMD_DIR/$SERVICE_NAME" | cut -d'=' -f2)"
        echo "  Working Directory: $(grep "^WorkingDirectory=" "$SYSTEMD_DIR/$SERVICE_NAME" | cut -d'=' -f2)"
        echo "  Enabled: $(systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || echo 'disabled')"
    else
        echo "  (Run with sudo to see full configuration)"
    fi
}

view_logs() {
    check_root
    
    if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME" ]; then
        echo -e "${RED}Error: Service is not installed. Please install it first.${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Viewing service logs (Press Ctrl+C to exit)...${NC}"
    echo
    journalctl -u "$SERVICE_NAME" -f
}

uninstall_service() {
    check_root
    
    if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME" ]; then
        echo -e "${YELLOW}Service is not installed${NC}"
        exit 0
    fi
    
    echo -e "${YELLOW}Uninstalling service...${NC}"
    echo
    
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$SERVICE_NAME"
    systemctl daemon-reload
    
    echo -e "${GREEN}Service uninstalled successfully${NC}"
}

while true; do
    print_header
    print_menu
    
    case $choice in
        1)
            setup_service
            ;;
        2)
            reload_service
            ;;
        3)
            start_service
            ;;
        4)
            stop_service
            ;;
        5)
            restart_service
            ;;
        6)
            show_status
            ;;
        7)
            view_logs
            ;;
        8)
            uninstall_service
            ;;
        9)
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Please try again.${NC}"
            ;;
    esac
    
    echo
    read -p "Press Enter to continue..."
    clear
done

