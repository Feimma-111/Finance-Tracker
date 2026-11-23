# Plan: moving the app to a Raspberry Pi

**Goal:** the app runs all the time on a small box at home, your Mac and phone just
open it in a browser, and your data exists in **3 copies in 2 places**:

1. the live database on the Pi,
2. daily backups copied to your Mac automatically,
3. one copy outside your home (an external drive kept elsewhere, or encrypted cloud storage).

The AI stays on your PC, and the Pi uses it whenever the PC is on, the same as now.

```
Phone / Mac ──Tailscale (encrypted)──> Pi: app + database ──Tailscale──> PC: Ollama (when on)
                                         │
                                         └── nightly backups ──> Mac ──> external drive
```

## What to buy (about $120–150)

| Part | Why |
|---|---|
| Raspberry Pi 5, 4 GB | Plenty for this app, and room for more later |
| Official 27 W USB-C power supply | Weaker supplies cause random crashes |
| Case with active cooler | Keeps it from throttling |
| M.2 HAT+ and a 128–256 GB NVMe SSD | **Don't run a database on an SD card.** They wear out and corrupt. |
| Ethernet cable to the router | More reliable than Wi-Fi |

## 1. Set up the Pi (about 30 minutes)

1. Use **Raspberry Pi Imager** to install **Raspberry Pi OS Lite (64-bit)**
   onto the SSD. In the Imager's settings, set:
   - hostname `finance-pi`
   - your username
   - **SSH with a public key only, no password**
2. Boot it and SSH in. Then turn on automatic security updates:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   ```
   ```bash
   sudo apt install -y unattended-upgrades git python3-venv
   ```
   ```bash
   sudo dpkg-reconfigure -plow unattended-upgrades
   ```
3. Install **Tailscale**, sign in with the same account as your other devices,
   and turn on Tailscale SSH:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   ```
   ```bash
   sudo tailscale up --ssh
   ```
4. **Don't forward any ports on your router.** Everything goes through Tailscale.

## 2. Install the app

```bash
git clone https://github.com/Feimma-111/Finance-Tracker.git
```
```bash
cd Finance-Tracker
```
```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
```

Build the website on your **Mac**, then copy it over (it's faster than
installing Node on the Pi):

```bash
cd frontend && npm run build && cd ..
```
```bash
scp -r frontend/dist finance-pi:Finance-Tracker/frontend/
```

## 3. Move your data (about 5 minutes)

1. **Quit the app on the Mac** (close its Terminal window), so nothing else
   writes to the database during the copy.
2. On the **Pi**, create the data folder and make it private:
   ```bash
   mkdir -p ~/.local/share/finance-tracker && chmod 700 ~/.local/share/finance-tracker
   ```
3. On the **Mac**, copy the database over:
   ```bash
   scp "$HOME/Library/Application Support/Finance Tracker/finance.db" finance-pi:.local/share/finance-tracker/
   ```
   Your passcode, settings, and AI address move with it.
4. Keep the Mac's copy until you've checked that everything shows up on the Pi.

## 4. Run it all the time

Install the service file from `deploy/finance-tracker.service`. It starts the app
at boot, restarts it if it crashes, and locks down what the app can touch.

```bash
sudo cp deploy/finance-tracker.service /etc/systemd/system/
```
```bash
sudo sed -i "s/YOUR_USER/$USER/g" /etc/systemd/system/finance-tracker.service
```
```bash
sudo systemctl enable --now finance-tracker
```
```bash
sudo tailscale serve --bg 8000
```

Your app's new address is **https://finance-pi.<your-tailnet>.ts.net**. On your
phone, remove the old home-screen icon and install it again from the new
address.

Then retire the Mac's server: turn off its serve with
`tailscale serve --https=443 off`, and stop using Finance Tracker.command. The
Mac becomes just a browser.

## 5. Backups to the Mac, plus one copy elsewhere

The Pi already makes daily backups. `deploy/pull-backups.sh` copies them to
your Mac. Run it by hand, or have macOS run it daily (instructions are in the
script). After that, back up the Mac (Time Machine to an external drive) or
copy the folder to encrypted cloud storage now and then. That's the third copy.

## Updating the app later

```bash
cd ~/Finance-Tracker && git pull && .venv/bin/python -m pip install -r requirements.txt
```
```bash
sudo systemctl restart finance-tracker
```

If the update changed the website, build `frontend/dist` on the Mac and `scp` it
over again before restarting.

## Security notes

- The Pi runs nothing but this app, Tailscale, and SSH, so there's very little to
  attack. Automatic updates keep the OS patched.
- Its SSD isn't encrypted by default. It stays at home, but if you want
  encryption at rest like FileVault, set up LUKS on the SSD. That's an extra
  step and it means typing a password at each boot, so it's optional.
- Nothing is exposed to the internet: `tailscale serve`, never `funnel`.
