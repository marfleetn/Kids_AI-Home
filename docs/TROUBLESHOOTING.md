# Kids AI Home — Troubleshooting Guide

## Network Access from LAN Devices

### Symptom: "Site can't be reached" / "took too long to respond" from phones, laptops, or Chromebooks

This platform runs inside Docker Desktop on Windows with WSL2. Docker Desktop WSL2 does **not** bind container ports to the host network adapter — it only binds to `localhost`. To make the service reachable from other devices on your LAN, you need a port forwarding rule and firewall configuration.

---

### Step 1: Verify Docker is running

```powershell
docker ps
```

You should see the `kids-ai-server` container running. If not:

```powershell
docker compose up -d
```

### Step 2: Set up port forwarding (netsh portproxy)

Docker Desktop WSL2 only listens on `127.0.0.1`. Use `netsh portproxy` to forward external traffic to Docker (run PowerShell as **Administrator**):

```powershell
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8090 connectaddress=127.0.0.1 connectport=8085
```

This forwards `0.0.0.0:8090` (all network interfaces) to `127.0.0.1:8085` (Docker's mapped port).

**Verify it's set up:**

```powershell
netsh interface portproxy show all
```

Expected output:

```
Listen on ipv4:             Connect to ipv4:
Address         Port        Address         Port
--------------- ----------  --------------- ----------
0.0.0.0         8090        127.0.0.1       8085
```

**Note:** This rule can be lost after a Windows reboot. Re-run the `add` command if needed, or create a startup script.

### Step 3: Configure Windows Firewall

Allow inbound TCP traffic on port 8090 (PowerShell as **Administrator**):

```powershell
New-NetFirewallRule -DisplayName "Kids AI 8090" -Direction Inbound -Protocol TCP -LocalPort 8090 -Action Allow -Profile Any
```

**Verify:**

```powershell
Get-NetFirewallRule -DisplayName "Kids AI 8090" | Format-List DisplayName, Enabled, Profile, Direction, Action
```

Expected:

```
DisplayName : Kids AI 8090
Enabled     : True
Profile     : Any
Direction   : Inbound
Action      : Allow
```

### Step 4: Enable ICMP ping (recommended)

By default, Windows blocks incoming ping requests. Other devices may fail to reach your PC if ICMP is disabled — and some network stacks behave unpredictably when ping is blocked. Enable it:

```powershell
netsh advfirewall firewall set rule name="File and Printer Sharing (Echo Request - ICMPv4-In)" new enable=yes
```

**This was confirmed as the root cause when devices on the same subnet could not connect, even with the correct firewall rule and portproxy in place.** Enabling ICMP resolved the issue.

### Step 5: Check your network profile

Windows Firewall treats Private and Public networks differently. Your home network should be set to **Private**:

```powershell
Get-NetConnectionProfile
```

If it shows **Public**, change it:

```powershell
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```

Replace `"Wi-Fi"` with your actual interface name (could be `"Ethernet"`, etc.).

### Step 6: Find your host PC's IP address

```powershell
ipconfig | findstr "IPv4"
```

Use this IP from other devices: `http://<host-ip>:8090`

**Tip:** Set a static IP or DHCP reservation on your router so the address doesn't change.

---

## Diagnostic Commands Reference

| What to check | Command | Run on |
|---|---|---|
| Docker container running | `docker ps` | Host PC |
| Port 8090 listening | `netstat -an \| findstr 8090` | Host PC |
| Port 8085 listening (Docker) | `netstat -an \| findstr 8085` | Host PC |
| Portproxy rules | `netsh interface portproxy show all` | Host PC (Admin) |
| Firewall rule exists | `Get-NetFirewallRule -DisplayName "Kids AI 8090"` | Host PC (Admin) |
| Firewall rule port filter | `Get-NetFirewallRule -DisplayName "Kids AI 8090" \| Get-NetFirewallPortFilter` | Host PC (Admin) |
| Network profile | `Get-NetConnectionProfile` | Host PC |
| Host PC IP address | `ipconfig \| findstr "IPv4"` | Host PC |
| Ping from client device | `ping <host-ip>` | Laptop/Chromebook |
| ICMP ping rules | `netsh advfirewall firewall show rule name="File and Printer Sharing (Echo Request - ICMPv4-In)"` | Host PC (Admin) |

---

## Common Issues

### "Destination host unreachable" when pinging from another device

**Cause:** Windows Firewall is blocking ICMP ping replies. Even if your port-specific rule is correct, blocked ICMP can prevent devices from establishing connectivity.

**Fix:** Enable ICMP ping (see Step 4 above).

### Portproxy rule disappears after reboot

**Cause:** `netsh portproxy` rules are generally persistent across reboots, but can be lost after major Windows updates or network stack resets.

**Fix:** Re-run the `netsh interface portproxy add` command (Step 2). Consider adding it to a startup script via Task Scheduler.

### Host PC IP address changed

**Cause:** DHCP assigned a new IP address after a router reboot or lease expiry.

**Fix:** Check with `ipconfig | findstr "IPv4"` and update the URL used by devices. Set a static IP or DHCP reservation on your router to prevent this.

### Chromebook blocked by Google Family Link

**Cause:** Family Link restricts which sites children can visit. IP addresses with ports may be blocked by default.

**Fix:** In the Family Link app on a parent's phone:
1. Select the child's profile
2. Go to **Controls** > **Content restrictions** > **Google Chrome**
3. Under **Approved sites**, add `http://<host-ip>:8090`

Repeat for each child's profile.

### "Connection refused" (instant error, not timeout)

**Cause:** The service is not running, or the port forwarding is misconfigured.

**Fix:**
1. Verify Docker is running: `docker ps`
2. Verify portproxy: `netsh interface portproxy show all`
3. Test locally first: `http://localhost:8085` (Docker direct) and `http://localhost:8090` (via portproxy)

### "Connection error. Please try again" in chat

**Cause:** The FastAPI server cannot reach the Ollama server.

**Fix:**
1. Verify Ollama is running on the Ollama server
2. Check the `OLLAMA_URL` in `.env` or `docker-compose.yml` points to the correct IP and port
3. Ensure Ollama is listening on all interfaces: `OLLAMA_HOST=0.0.0.0`
4. Test from the Docker host: `curl http://<ollama-ip>:11434/api/tags`

---

## Port Mapping Summary

```
LAN Device                    Host PC (Windows)               Docker Container
─────────────────────────────────────────────────────────────────────────────────
http://<host-ip>:8090  ──►  portproxy 0.0.0.0:8090  ──►  127.0.0.1:8085  ──►  container:8090
                              (netsh)                    (docker port map)      (uvicorn)
```

## Checking GPU vs CPU Processing

If your Ollama server has a GPU, verify the model is running on it:

```bash
# In the terminal on your Ollama server
ollama ps
```

The **PROCESSOR** column shows `100% GPU` or `100% CPU`.

For real-time GPU usage during a chat:

```bash
nvidia-smi
```

If the model is running on CPU when it should be on GPU:

```bash
sudo systemctl restart ollama
```

Then send a chat message and check `ollama ps` again.
