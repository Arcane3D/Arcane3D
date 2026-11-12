# Image to DXF — Oracle Cloud Always Free deployment

This repository contains the supplied Python image-to-DXF converter and its HTTP MCP server. The deployment target documented here is a self-managed Ubuntu ARM64 VM on Oracle Cloud Infrastructure (OCI) **Always Free-eligible resources only**.

## Important billing and signup limitation

Oracle states that most Free Tier signups require a valid credit or debit card for identity verification. It may place a temporary authorization hold; Oracle says these holds are removed by the bank and are not actual charges. If you cannot provide a card or cannot accept even a temporary authorization hold, stop: you may not be able to create a new OCI account under that constraint.

Do not upgrade the tenancy to Pay As You Go or Monthly Flex. Do not create resources that are not explicitly marked **Always Free eligible**. If the Console shows a non-zero estimate or unclear billing status for any required resource, cancel and do not create it.

The repository's setup script installs software on a VM you have already created. It does not create an OCI account, VM, network, public IP, DNS zone, or other cloud resource.

## Current Always Free limits to check

Oracle's current Always Free documentation lists these limits (subject to the Console's actual eligibility labels and tenancy quota):

- **Ampere A1 Compute:** up to 2 OCPUs and 12 GB RAM total, in the tenancy's home region.
- **Block Volume:** 200 GB total for boot and block volumes combined; the default VM boot volume counts against this.
- **Outbound data transfer:** up to 10 TB/month.
- **Object Storage:** 20 GB in an Always Free-only account; this project does not require it.

The recommended VM configuration for this converter is one `VM.Standard.A1.Flex` instance with **1 OCPU and 6 GB RAM**, an Ubuntu ARM64 image explicitly labelled **Always Free eligible**, and the default 50 GB boot volume. This is within the published A1 and storage allowances. Do not increase the VM beyond the tenancy's visible Always Free limits.

Always Free compute can be reclaimed if Oracle's idle-instance conditions are met over a seven-day period. It is not a guaranteed-uptime service.

Official references:
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- https://www.oracle.com/cloud/free/faq/
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm

## Architecture

```text
GitHub: Arcane3D/Arcane3D
        |
        v
OCI Ubuntu ARM64 VM (A1 Flex, Always Free eligible)
        |
        +-- Docker Compose
              |
              +-- Caddy :80/:443 (automatic HTTPS)
              |       |
              |       +-- reverse proxy
              |
              +-- FastAPI MCP server :8787 (private Docker network)
                      |
                      +-- SQLite /data/app.db
                      +-- DXF files /data/files
```

SQLite and generated DXF files live in a named Docker volume so they survive container rebuilds. Caddy's certificate state is also stored in a named volume. The API port 8787 is not published to the internet.

## Before creating the VM

1. Sign in to an existing OCI Free Tier tenancy. If you do not already have one and cannot supply the card Oracle requires for identity verification, stop here.
2. Select the tenancy's **home region**. Always Free compute and block-volume resources must be created there.
3. In Compute, create a VM using shape `VM.Standard.A1.Flex`, with 1 OCPU and 6 GB memory. Check the **Always Free eligible** label in the Console before continuing.
4. Select an Ubuntu ARM64 image labelled **Always Free eligible**.
5. Keep the default 50 GB boot volume. It is part of the combined 200 GB Always Free boot/block volume allowance.
6. For a public MCP endpoint, a reachable public IP and inbound HTTPS are needed. Oracle's Always Free resource table does not spell out a separate public-IP allowance for every A1 configuration. Before creating/assigning an IP, verify in the Console that the exact IP/network resources are free for your tenancy. If the Console shows a charge or you cannot confirm that it is free, do not proceed.
7. Create or use a public subnet with an internet gateway only after checking that every resource in the creation summary is free. Configure inbound security rules for TCP 80 and 443. Allow SSH TCP 22 only from your own current public IP. Do not expose TCP 8787.
8. Attach your SSH public key. Keep the private key on your own computer.
9. Do not create a paid load balancer, NAT gateway, extra block volume, paid image, or other non-free item.

For an internet-facing service, you also need a DNS name under a domain you control. Point its A record to the VM's verified public IPv4 address (or use an IPv6 record only if you have deliberately configured and tested public IPv6 connectivity). A free dynamic-DNS subdomain may be used if its provider allows the required DNS record. Caddy obtains and renews HTTPS certificates automatically when the domain resolves to the VM and ports 80/443 are reachable.

## Deploy on the VM

From your local computer, SSH to the Ubuntu VM:

```bash
ssh -i /path/to/your-private-key ubuntu@YOUR_VM_PUBLIC_IP
```

After confirming DNS for your chosen hostname points to this VM, run:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/Arcane3D/Arcane3D/main/scripts/install-oracle-vm.sh)" -- your.dns.name
```

The script:
- verifies that the host is Ubuntu;
- installs Docker Engine and the Docker Compose plugin from Docker's official Ubuntu repository;
- clones or updates this public GitHub repository under `/opt/image-to-dxf`;
- generates a unique `SECRET_KEY` locally on the VM;
- writes a private `.env` file with the domain and persistent data paths;
- opens the host firewall for SSH, HTTP and HTTPS (the OCI VCN security rules must also allow 80/443);
- builds and starts the API and Caddy containers.

You can also clone the repo first and run the checked-in script:

```bash
git clone https://github.com/Arcane3D/Arcane3D.git
cd Arcane3D
sudo bash scripts/install-oracle-vm.sh your.dns.name
```

The script does not ask for or store your OCI credentials. It does not select a VM shape, create infrastructure, or change your account billing status.

## Verify the service

On the VM:

```bash
cd /opt/image-to-dxf
sudo docker compose ps
sudo docker compose logs --tail=100 api caddy
curl -fsS https://YOUR_DNS_NAME/
```

The root endpoint should return JSON with the service name and MCP URL. The actual MCP endpoint is:

```text
https://YOUR_DNS_NAME/mcp
```

In ChatGPT, add/connect a custom MCP server using that exact HTTPS URL and complete OAuth sign-up/login. Do not use the GitHub repository URL as the MCP URL. Use only OAuth callback URLs shown by ChatGPT; update `ALLOWED_REDIRECTS` in `.env` if ChatGPT displays a different callback, then run `sudo docker compose up -d`.

## Updating the application

The named Docker volumes are preserved during application updates:

```bash
cd /opt/image-to-dxf
sudo git pull --ff-only
sudo docker compose up -d --build
```

## Backing up persistent data

The `app_data` volume contains both the SQLite account database and generated DXF files. Back it up before changing the VM, Docker volumes, or authentication code:

```bash
cd /opt/image-to-dxf
sudo mkdir -p /opt/image-to-dxf-backups
sudo docker run --rm \
  -v image-to-dxf_app_data:/data:ro \
  -v /opt/image-to-dxf-backups:/backup \
  alpine:3.20 \
  sh -c 'tar -czf /backup/image-to-dxf-data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz -C /data .'
```

The exact volume name is based on the Compose project name. Check it with `sudo docker volume ls` if you changed the directory or Compose project name.

## Environment variables

The installation script creates `.env` with:

- `PUBLIC_DOMAIN`: DNS hostname for the service.
- `SECRET_KEY`: generated random HMAC secret (never commit or share it).
- `ALLOWED_REDIRECTS`: comma-separated OAuth redirect URI allow-list.
- The Compose file sets `BASE_URL` to `https://PUBLIC_DOMAIN`, and stores SQLite and DXF files below `/data`.

Never commit `.env`, database files, or converted DXF files.

## MCP tool

Tool name: `image_to_dxf`

- `image`: attached file metadata with `download_url`, `file_id`, and optional `mime_type` / `file_name`.
- `width_mm`: finished drawing width (1–5000 mm; default 100).
- `threshold`: raster threshold (0 selects automatically; 1–254 sets it explicitly).
- `invert`: trace light artwork on a dark background.
- `tolerance_mm`: outline simplification tolerance (default 0.1 mm).

## Known limitations and security notes

- This traces outlines/silhouettes; it does not create engraving centerlines. Photos usually need preprocessing. SVG text should be converted to paths.
- Remote input download is limited to 15 MB; raster images are limited to 40 megapixels. Output links expire after one hour.
- The supplied authentication is starter-grade: no email verification, password reset, or shared rate limiting. Review and harden it before exposing it to broad public traffic.
- The file-fetch implementation should receive a security review for DNS rebinding/SSRF risks before public production use.
- DXF geometry must be checked in the target CAD/laser software for dimensions, closed contours, kerf, material, and machine settings. The service does not certify physical laser readiness.
- Oracle may reclaim idle Always Free compute under its documented idle-use policy. Free Tier does not include an SLA.
