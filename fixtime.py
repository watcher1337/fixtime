#!/usr/bin/env python3
import os
import sys
import platform
import subprocess
import argparse
import socket
import threading
import time as ttime
import re
import warnings
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import concurrent.futures

# ============================================================
# Terminal Colors
# ============================================================

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLACK = "\033[30m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

def supports_color():
    """Return True if terminal likely supports ANSI colors."""
    if os.getenv("NO_COLOR") is not None:
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    if platform.system().lower() == "windows":
        return (os.getenv("ANSICON") is not None or
                os.getenv("WT_SESSION") is not None or
                os.getenv("TERM_PROGRAM") == "vscode" or
                os.getenv("TERM") is not None)
    return True

USE_COLOR = supports_color()

def color(text, code):
    if not USE_COLOR:
        return str(text)
    return f"{code}{text}{Color.RESET}"

def bold(text): return color(text, Color.BOLD)
def red(text): return color(text, Color.RED)
def green(text): return color(text, Color.GREEN)
def yellow(text): return color(text, Color.YELLOW)
def blue(text): return color(text, Color.BLUE)
def cyan(text): return color(text, Color.CYAN)
def magenta(text): return color(text, Color.MAGENTA)
def dim(text): return color(text, Color.DIM)

def colorize_message(message):
    message = str(message)
    prefixes = (("[✓]", Color.GREEN), ("[✗]", Color.RED), ("[!]", Color.YELLOW))
    for prefix, prefix_color in prefixes:
        if message.startswith(prefix):
            colored_prefix = color(prefix, prefix_color)
            return f"{colored_prefix}{message[len(prefix):]}"
    return message

def cprint(*values, **kwargs):
    """Replacement for print() that colors known status prefixes."""
    if not values:
        print(**kwargs)
        return
    values = list(values)
    if isinstance(values[0], str):
        values[0] = colorize_message(values[0])
    print(*values, **kwargs)

def print_value(label, value, indent=4):
    """Print a label/value pair with cyan label and bold value."""
    spaces = " " * indent
    print(f"{spaces}{cyan(f'{label:<16}')}{bold(value)}")

def print_separator(char="=", length=60):
    print(dim(char * length))

# ============================================================
# Platform detection - FULL ARM SUPPORT
# ============================================================

def detect_os():
    """Detect OS and architecture with full ARM support."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == "windows":
        return "windows"
    elif system == "darwin":
        # Check if running on Apple Silicon (ARM)
        if machine in ["arm64", "aarch64"]:
            return "darwin_arm"
        return "darwin"
    else:
        # Linux - check if ARM
        if machine in ["arm64", "aarch64", "armv7l", "armv8l"]:
            return "linux_arm"
        return "linux"

def is_arm():
    """Check if running on ARM architecture."""
    return detect_os() in ["darwin_arm", "linux_arm"]

def is_arm_mac():
    """Check if running on Apple Silicon Mac."""
    return detect_os() == "darwin_arm"

def is_linux_arm():
    """Check if running on Linux ARM."""
    return detect_os() == "linux_arm"

OS_NAME = detect_os()
IS_ARM = is_arm()
IS_ARM_MAC = is_arm_mac()
IS_LINUX_ARM = is_linux_arm()

# ============================================================
# OS-specific helpers with ARM support
# ============================================================

def is_admin():
    """Return True if running with admin/root privileges."""
    if OS_NAME == "windows":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return os.system("sudo -n true") == 0

def run_privileged(cmd, **kwargs):
    """Run a command, using sudo on Unix if needed."""
    if OS_NAME != "windows" and not is_admin():
        if isinstance(cmd, str):
            cmd = f"sudo {cmd}"
        else:
            cmd = ["sudo"] + cmd
    return subprocess.run(cmd, **kwargs)

# ============================================================
# OS-specific time functions with ARM support
# ============================================================

def disable_ntp():
    """Disable automatic NTP sync."""
    if OS_NAME == "windows":
        return True
    elif OS_NAME in ["darwin", "darwin_arm"]:
        result = run_privileged(
            ["systemsetup", "-setusingnetworktime", "off"],
            capture_output=True, text=True, check=False
        )
        return result.returncode == 0
    else:
        # Linux (both x86 and ARM)
        result = run_privileged(
            ["timedatectl", "set-ntp", "off"],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            # Fallback for older systems
            result = run_privileged(
                ["systemctl", "stop", "ntp"],
                capture_output=True, text=True, check=False
            )
        return result.returncode == 0

def enable_ntp():
    """Re-enable automatic NTP sync."""
    if OS_NAME == "windows":
        return True
    elif OS_NAME in ["darwin", "darwin_arm"]:
        result = run_privileged(
            ["systemsetup", "-setusingnetworktime", "on"],
            capture_output=True, text=True, check=False
        )
        return result.returncode == 0
    else:
        # Linux (both x86 and ARM)
        result = run_privileged(
            ["timedatectl", "set-ntp", "on"],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            # Fallback for older systems
            result = run_privileged(
                ["systemctl", "start", "ntp"],
                capture_output=True, text=True, check=False
            )
        return result.returncode == 0

def set_timezone_utc():
    """Set system timezone to UTC."""
    if OS_NAME == "windows":
        result = subprocess.run(["tzutil", "/s", "UTC"],
                               capture_output=True, text=True, check=False)
        return result.returncode == 0
    elif OS_NAME in ["darwin", "darwin_arm"]:
        for tz in ["UTC", "Etc/UTC", "GMT", "GMT0"]:
            result = run_privileged(
                ["systemsetup", "-settimezone", tz],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                return True
        return False
    else:
        # Linux (both x86 and ARM)
        result = run_privileged(
            ["timedatectl", "set-timezone", "UTC"],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            # Fallback for older systems
            result = run_privileged(
                ["ln", "-sf", "/usr/share/zoneinfo/UTC", "/etc/localtime"],
                capture_output=True, text=True, check=False
            )
        return result.returncode == 0

def set_system_time(dt):
    """Set system time to given datetime object (assumed UTC)."""
    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    
    if OS_NAME == "windows":
        cmd = ["powershell", "-Command", f'Set-Date -Date "{time_str}"']
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.returncode == 0
    elif OS_NAME in ["darwin", "darwin_arm"]:
        # macOS date format
        cmd = ["date", "-u", time_str]
        result = run_privileged(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            # Try alternative format
            cmd = ["date", "-u", dt.strftime("%Y%m%d%H%M.%S")]
            result = run_privileged(cmd, capture_output=True, text=True, check=False)
        return result.returncode == 0
    else:
        # Linux (both x86 and ARM)
        cmd = ["date", "-u", "-s", time_str]
        result = run_privileged(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            # Try alternative format for older systems
            cmd = ["date", "-u", dt.strftime("%m%d%H%M%Y.%S")]
            result = run_privileged(cmd, capture_output=True, text=True, check=False)
        return result.returncode == 0

def run_ntp_sync(server):
    """Synchronize time using NTP (platform-aware)."""
    if OS_NAME == "windows":
        config_cmd = ["w32tm", "/config", "/manualpeerlist", server,
                     "/syncfromflags:manual", "/update"]
        subprocess.run(config_cmd, capture_output=True, check=False)
        result = subprocess.run(["w32tm", "/resync", "/nowait"],
                               capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return True
        result2 = subprocess.run(["net", "time", "\\\\" + server, "/set", "/y"],
                                capture_output=True, text=True, check=False)
        return result2.returncode == 0
    elif OS_NAME in ["darwin", "darwin_arm"]:
        # macOS NTP sync
        for tool in ["sntp", "ntpdate", "chronyc"]:
            if tool == "sntp":
                disable_ntp()
                cmd = ["sntp", "-sS", server]
                result = run_privileged(cmd, capture_output=True, text=True, check=False)
                enable_ntp()
                if result.returncode == 0:
                    return True
            elif tool == "ntpdate":
                disable_ntp()
                cmd = ["ntpdate", server]
                result = run_privileged(cmd, capture_output=True, text=True, check=False)
                enable_ntp()
                if result.returncode == 0:
                    return True
            elif tool == "chronyc":
                cmd = ["chronyc", "-a", "makestep"]
                result = run_privileged(cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    return True
        return False
    else:
        # Linux (both x86 and ARM)
        # Check if chrony is available (common on ARM)
        for tool in ["ntpdate", "sntp", "chronyc", "ntp"]:
            if tool == "ntpdate":
                disable_ntp()
                cmd = ["ntpdate", server]
                result = run_privileged(cmd, capture_output=True, text=True, check=False)
                enable_ntp()
                if result.returncode == 0:
                    return True
            elif tool == "sntp":
                cmd = ["sntp", "-s", server]
                result = run_privileged(cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    return True
            elif tool == "chronyc":
                cmd = ["chronyc", "-a", "makestep"]
                result = run_privileged(cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    return True
            elif tool == "ntp":
                cmd = ["ntpdate", "-u", server]
                result = run_privileged(cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    return True
        return False

# ============================================================
# Imports with ARM support
# ============================================================

try:
    from impacket.smbconnection import SMBConnection
except ImportError:
    if OS_NAME in ["darwin", "darwin_arm"]:
        cprint("[-] Required module 'impacket' not found.")
        cprint("[*] Install on macOS with:")
        cprint("    brew install python3")
        cprint("    pip3 install impacket")
    elif OS_NAME == "linux_arm":
        cprint("[-] Required module 'impacket' not found.")
        cprint("[*] Install on Linux ARM with:")
        cprint("    sudo apt install python3-impacket")
        cprint("    or")
        cprint("    pip3 install impacket")
    else:
        cprint("[-] Required module 'impacket' not found. "
               "Install with: sudo apt install python3-impacket")
    sys.exit(1)

try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
except ImportError:
    class InsecureRequestWarning(Warning):
        pass

# ============================================================
# Configuration
# ============================================================

TIMEOUT = 3
MAX_WORKERS = 3
KERBEROS_MAX_SKEW = 300

print_lock = threading.Lock()

# ============================================================
# Arguments
# ============================================================

parser = argparse.ArgumentParser(
    description="Synchronization tool for AD Kerberos authentication in penetration testing",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    usage="fixtime.py [-h] [-i IP] [--force] [--restore]",
    add_help=False,
    epilog="""
Examples:
  fixtime -i 10.10.10.10                  # Sync with IP
  fixtime -i 10.10.10.10 --force          # Force sync with IP
  fixtime --restore                       # Restore NTP service
""",
)

parser.add_argument("-h", action="help", default=argparse.SUPPRESS,
                   help="show this help message")
parser.add_argument("-i", dest="ip", help="Target IP address")
parser.add_argument("--force", action="store_true",
                   help="Force time sync even if within Kerberos tolerance")
parser.add_argument("--restore", action="store_true",
                   help="Re-enable NTP")

# Hidden options
parser.add_argument("-u", "--url", help=argparse.SUPPRESS)
parser.add_argument("-d", "--domain", help=argparse.SUPPRESS)
parser.add_argument("-v", "--verbose", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--check-skew", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--use-ntpdate", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--auto-domain", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--skip-timezone", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--ntp-server", help=argparse.SUPPRESS)
parser.add_argument("--no-ntpdate-fallback", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--auto-ntpdate", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--no-color", action="store_true", help=argparse.SUPPRESS)

args = parser.parse_args()

if args.no_color:
    USE_COLOR = False

# ============================================================
# Logging
# ============================================================

def log(msg, force=False):
    if args.verbose or force:
        with print_lock:
            cprint(msg)

# ============================================================
# Domain helpers
# ============================================================

def extract_domain_from_hostname(hostname):
    if not hostname:
        return None
    hostname = str(hostname).lower()
    prefixes = [
        "dc.", "ad.", "adfs.", "exchange.", "mail.",
        "owa.", "www.", "ns.", "dns.", "ntp.", "time."
    ]
    for prefix in prefixes:
        if hostname.startswith(prefix):
            hostname = hostname[len(prefix):]
            break
    parts = hostname.split(".")
    if len(parts) >= 2:
        common_tlds = [
            "com", "net", "org", "edu", "gov",
            "mil", "io", "htb", "local", "lan", "corp"
        ]
        if parts[-1] in common_tlds:
            return hostname
        if not re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname):
            return ".".join(parts[-2:])
    return None

def get_ntp_server(target_ip, target_hostname):
    if args.ntp_server:
        return args.ntp_server
    if args.auto_domain or args.domain:
        domain = args.domain
        if not domain and args.auto_domain:
            domain = extract_domain_from_hostname(target_hostname)
        if domain:
            return domain
    return target_ip

# ============================================================
# Local time
# ============================================================

def get_local_time_info():
    try:
        local_now = datetime.now()
        utc_now = datetime.now(timezone.utc)
        timezone_info = "Unknown"
        if OS_NAME == "windows":
            try:
                result = subprocess.run(["tzutil", "/g"],
                                       capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    timezone_info = result.stdout.strip()
            except Exception:
                pass
        else:
            try:
                result = subprocess.run(["timedatectl", "status"],
                                       capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    lines = result.stdout.split("\n")
                    tz_line = [line for line in lines if "Time zone" in line]
                    if tz_line:
                        timezone_info = tz_line[0].split(":")[1].strip()
            except Exception:
                pass
        offset = utc_now - local_now.replace(tzinfo=timezone.utc)
        offset_hours = offset.total_seconds() / 3600
        return {
            "local": local_now,
            "utc": utc_now,
            "timezone": timezone_info,
            "offset_hours": offset_hours,
        }
    except Exception as e:
        log(f"[-] Failed to get local time info: {e}")
        return None

# ============================================================
# Restore NTP
# ============================================================

def restore_ntp():
    if enable_ntp():
        cprint("[✓] NTP restored successfully")
    else:
        cprint("[-] Failed to restore NTP")

# ============================================================
# Target validation
# ============================================================

def validate_url():
    if not args.url and args.ip:
        url = f"http://{args.ip}"
        hostname = args.ip
        target_ip = args.ip
        return url, hostname, target_ip
    url = args.url
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    parsed = urlparse(url)
    hostname = parsed.hostname or parsed.path.split(":")[0]
    if ":" in hostname:
        hostname = hostname.split(":")[0]
    if args.ip:
        target_ip = args.ip
    else:
        try:
            target_ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            target_ip = hostname
    return url, hostname, target_ip

# ============================================================
# Port checking
# ============================================================

def check_port(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except socket.gaierror:
        log(f"[-] DNS resolution failed for {host}")
        return False
    except Exception as e:
        log(f"[-] Port check for {host}:{port} failed: {e}")
        return False

# ============================================================
# NTP
# ============================================================

def run_ntpdate_sync(ntp_server):
    return run_ntp_sync(ntp_server)

def auto_ntpdate_sync(ntp_server):
    cprint(f"\n[🔧] Running automatic NTP sync with {cyan(ntp_server)}")
    cprint("[*] Using OS-specific NTP tools...")
    disable_ntp()
    success_result = run_ntp_sync(ntp_server)
    if OS_NAME != "windows":
        enable_ntp()
    if success_result:
        cprint("[✓] NTP sync successful")
    else:
        cprint("[-] NTP sync failed")
        if not args.no_ntpdate_fallback:
            fallback_servers = [
                "time.google.com",
                "time.windows.com",
                "pool.ntp.org",
            ]
            for server in fallback_servers:
                cprint(f"[*] Trying fallback NTP server: {cyan(server)}")
                if run_ntp_sync(server):
                    cprint(f"[✓] NTP sync successful with {cyan(server)}")
                    success_result = True
                    break
    return success_result

# ============================================================
# Remote Time - WinRM
# ============================================================

def get_time_winrm(url, host, ip=None):
    port = 5985
    target = ip if ip else host
    try:
        if not check_port(target, port):
            log(f"[-] Port {port} (WinRM) closed on {target}.")
            return None
        log(f"[*] Trying WinRM ({port}) on {target}")
        endpoints = ["/wsman", "/wsman/", ""]
        for endpoint in endpoints:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", InsecureRequestWarning)
                    if ip:
                        r = requests.head(
                            f"http://{ip}:{port}{endpoint}",
                            timeout=TIMEOUT, verify=False, allow_redirects=False
                        )
                    else:
                        r = requests.head(
                            f"{url}:{port}{endpoint}",
                            timeout=TIMEOUT, verify=False, allow_redirects=False
                        )
                if "Date" in r.headers:
                    date_str = r.headers["Date"]
                    try:
                        remote_time = datetime.strptime(
                            date_str, "%a, %d %b %Y %H:%M:%S %Z"
                        )
                        return (remote_time, f"WinRM (HTTP Date header) on {target}")
                    except ValueError:
                        try:
                            remote_time = datetime.strptime(
                                date_str, "%a, %d %b %Y %H:%M:%S GMT"
                            )
                            return (remote_time, f"WinRM (HTTP Date header) on {target}")
                        except Exception:
                            continue
            except requests.exceptions.RequestException:
                continue
        log(f"[-] WinRM: No valid Date header from {target}")
    except Exception as e:
        log(f"[-] WinRM failed on {target}: {type(e).__name__} - {e}")
    return None

# ============================================================
# Remote Time - SMB
# ============================================================

def get_time_smb(host, ip=None):
    port = 445
    target = ip if ip else host
    try:
        if not check_port(target, port):
            log(f"[-] Port {port} (SMB) closed on {target}.")
            return None
        log(f"[*] Trying SMB ({port}) on {target}")
        conn = SMBConnection(target, target, sess_port=port, timeout=TIMEOUT)
        server_time = conn.getSMBServer().get_server_time()
        conn.close()
        return (server_time, f"SMB on {target}")
    except Exception as e:
        log(f"[-] SMB failed on {target}: {type(e).__name__} - {e}")
    return None

# ============================================================
# Remote Time - HTTP / HTTPS
# ============================================================

def get_time_http(url, host, ip=None):
    port = 80
    target = ip if ip else host
    try:
        log(f"[*] Trying HTTP ({port}) on {target}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            r = requests.head(url, timeout=TIMEOUT, verify=False, allow_redirects=False)
        if "Date" in r.headers:
            date_str = r.headers["Date"]
            try:
                remote_time = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
                return (remote_time, f"HTTP Date header on {target}")
            except ValueError:
                try:
                    remote_time = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S GMT")
                    return (remote_time, f"HTTP Date header on {target}")
                except Exception:
                    pass
    except Exception:
        pass
    port = 443
    try:
        log(f"[*] Trying HTTPS ({port}) on {target}")
        https_url = url.replace("http://", "https://")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            r = requests.head(https_url, timeout=TIMEOUT, verify=False, allow_redirects=False)
        if "Date" in r.headers:
            date_str = r.headers["Date"]
            try:
                remote_time = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
                return (remote_time, f"HTTPS Date header on {target}")
            except ValueError:
                try:
                    remote_time = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S GMT")
                    return (remote_time, f"HTTPS Date header on {target}")
                except Exception:
                    pass
    except Exception:
        pass
    return None

# ============================================================
# Concurrent Remote Time
# ============================================================

def get_remote_time_concurrent(url, host, ip=None):
    tasks = [
        (get_time_winrm, (url, host, ip)),
        (get_time_smb, (host, ip)),
        (get_time_http, (url, host, ip)),
    ]
    found_result = None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_method = {
                executor.submit(func, *func_args): func.__name__
                for func, func_args in tasks
            }
            for future in concurrent.futures.as_completed(future_to_method):
                result = future.result()
                if result:
                    found_result = result
                    log(f"[+] Time found via {result[1]}")
                    for f in future_to_method.keys():
                        if not f.done():
                            f.cancel()
                    break
    except KeyboardInterrupt:
        log("\n[-] Interrupted by user")
        raise
    return found_result

# ============================================================
# Skew Calculation
# ============================================================

def calculate_skew(local_time, remote_time):
    if local_time.tzinfo is None:
        local_time = local_time.replace(tzinfo=timezone.utc)
    if remote_time.tzinfo is None:
        remote_time = remote_time.replace(tzinfo=timezone.utc)
    skew = abs((remote_time - local_time).total_seconds())
    signed_skew = (remote_time - local_time).total_seconds()
    return {
        "absolute_seconds": skew,
        "signed_seconds": signed_skew,
        "within_kerberos_tolerance": skew <= KERBEROS_MAX_SKEW,
        "local_ahead": signed_skew < 0,
        "remote_ahead": signed_skew > 0,
    }

# ============================================================
# Manual Time Synchronization
# ============================================================

def sync_time_manual(remote_time_tuple, ntp_server):
    if remote_time_tuple is None:
        return False
    remote_time_obj, method = remote_time_tuple
    try:
        if remote_time_obj.tzinfo is None:
            remote_time_obj = remote_time_obj.replace(tzinfo=timezone.utc)
        remote_utc = remote_time_obj.astimezone(timezone.utc)
        local_info = get_local_time_info()
        skew_info = calculate_skew(
            local_info["local"] if local_info else datetime.now(),
            remote_time_obj,
        )
        if skew_info["within_kerberos_tolerance"] and not args.force:
            return True
        if args.check_skew:
            return True
        if not args.skip_timezone:
            set_timezone_utc()
        if OS_NAME != "windows":
            disable_ntp()
        if set_system_time(remote_utc):
            if args.use_ntpdate and ntp_server:
                run_ntp_sync(ntp_server)
            ttime.sleep(1)
            new_local = datetime.now(timezone.utc)
            new_skew = calculate_skew(new_local, remote_time_obj)
            cprint("[✓] Time synced successfully!")
            return True
        else:
            cprint("[-] Failed to set time")
            return False
    except Exception as e:
        cprint(f"[-] Sync failed: {type(e).__name__} - {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return False

# ============================================================
# Main
# ============================================================

def main():
    # Display architecture info in verbose mode
    if args.verbose:
        cprint(f"[*] OS: {OS_NAME}")
        cprint(f"[*] Architecture: {platform.machine()}")
        if IS_ARM:
            cprint(f"[*] ARM detected: {IS_ARM_MAC and 'Apple Silicon' or 'Linux ARM'}")

    try:
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    except Exception:
        pass

    if args.restore:
        restore_ntp()
        return

    if not args.url and not args.ip and not args.restore:
        parser.error("Either -u/--url or -i is required")

    if args.check_skew and not args.url and not args.ip:
        parser.error("Either -u/--url or -i is required with --check-skew")

    if args.url or args.ip:
        url, hostname, target_ip = validate_url()
        ntp_server = get_ntp_server(target_ip, hostname)

        if args.auto_ntpdate:
            print()
            print_separator()
            cprint("[🚀] Starting automatic NTP synchronization...")
            print_separator()
            auto_ntpdate_sync(ntp_server)
            print_separator()
            cprint("[✅] Auto NTP sync completed")
            print_separator()
            print()

        try:
            result = get_remote_time_concurrent(url, hostname, target_ip)
            if result:
                remote_time, method = result
                if args.check_skew:
                    skew_info = calculate_skew(datetime.now(), remote_time)
                    cprint("\n[+] Time Skew Analysis:")
                    print_value("Remote time:", remote_time.strftime("%Y-%m-%d %H:%M:%S"))
                    print_value("Source:", method)
                    print_value("Difference:", f"{skew_info['absolute_seconds']:.2f} seconds")
                    if skew_info["within_kerberos_tolerance"]:
                        cprint("[✓] Within Kerberos tolerance")
                    else:
                        cprint("[!] Exceeds Kerberos tolerance")
                else:
                    success_result = sync_time_manual(result, ntp_server)
                    if not success_result:
                        cprint("\n[-] Time sync failed")
                        if ntp_server:
                            cprint("[*] Try auto NTP sync:")
                            print("    " + cyan(
                                f"{sys.argv[0]} -i {target_ip} --auto-ntpdate"
                            ))
            else:
                cprint("\n[-] Failed to fetch remote time from target")
        except KeyboardInterrupt:
            cprint("\n[-] Operation cancelled")
            sys.exit(1)
        except Exception as e:
            cprint(f"\n[-] Error: {type(e).__name__} - {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    main()