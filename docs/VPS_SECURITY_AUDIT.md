# VPS Security Audit

Audit snapshot for the OpenClaw VPS `46.225.98.179` on March 9, 2026.

## Executive Summary

The VPS is not "blindé". It has several strong baseline controls, but it also carries meaningful operational and security risk because multiple products and agents cohabit on one host and several services still run as `root`. The good news is that the host firewall defaults to deny inbound traffic, Fail2Ban is enabled, the Le Filon stack has now been moved off this host, and the main internal APIs were rebound to loopback on March 9, 2026.

Removed or migrated during this pass:

- `/root/openclaw-staging`
- Le Filon Docker stack moved to `46.225.173.203`

There should now be no `lefilon*` containers on `46.225.98.179`.
Public Filon DNS is now aligned with the dedicated VPS through Cloudflare.

## Findings

### High

1. Multi-tenant blast radius on one VPS

The same host currently runs:

- TorahCode continuous runner
- YouTube pipeline
- OpenClaw trading agent
- Parnassa Rust hotpath
- Ollama
- Dexter Research
- Zeroclaw

Impact: a compromise or resource exhaustion in one stack can degrade or expose the others. This is the dominant systemic risk on the box.

### Medium

2. Multiple services run as `root`

Observed examples:

- `youtube-pipeline.service`
- `openclaw.service`
- OpenClaw shell tooling under `/root/openclaw`

Impact: any RCE in those services lands directly in a privileged context, increasing host takeover risk.

3. Root-run services remain the main exposed trust boundary

Current state after hardening:

- `127.0.0.1:18080` for `parnassa-rust-hotpath`
- `127.0.0.1:3847` for `youtube-pipeline`

Additional detail:

- the previous Filon-associated listener on `3070` is now gone from this host
- the earlier special-case `ufw` allow for `18080/tcp` from `172.20.0.0/16` was removed

This substantially reduces accidental network exposure, but the services are still sensitive because compromise of local root or same-host workloads can still reach them.

4. Authentication and rate-limit instability in `openclaw-agent`

Recent service logs show:

- `401` on some KV writes
- repeated `429`

Impact: degraded integrity/availability of the trading-control path and weak confidence in current auth/rate-limit handling.

5. Availability risk from disk pressure was real today

The YouTube pipeline had been failing all cron runs because disk free space fell below its own `2GB` safety threshold. This is primarily an availability issue, but persistent near-full disks also make recovery and forensics worse.

### Low

6. `openclaw.service` being `active (exited)` is expected, but easy to misread

This unit is a `Type=oneshot` Docker Compose wrapper with `RemainAfterExit=yes`. It is not an inactive broken service. It is operationally valid, but the status can confuse future operators.

## Baseline Controls Seen

- `ufw` active with default deny inbound
- `fail2ban` active
- `sshd` protected by Fail2Ban chain
- only `22/tcp` publicly allowed at the host firewall level
- `youtube-pipeline` and `parnassa-rust-hotpath` rebound to loopback on March 9, 2026
- YouTube pipeline mutations require bearer auth

## OpenClaw Inventory

Active OpenClaw-related items seen:

- `openclaw-agent.service`
- `openclaw-rust-hotpath.service`
- `openclaw.service` as a Docker Compose bootstrap unit
- Docker container `openclaw-sentinel`

Inactive residue removed:

- `/root/openclaw-staging`

No stopped OpenClaw Docker containers were found during this pass.

## Recommended Next Steps

1. Keep internal services on `127.0.0.1` unless a public or cross-host consumer is explicitly required.
2. Run application services under dedicated non-root users.
3. Split high-risk workloads across at least two hosts or two trust zones.
4. Add explicit monitoring for disk free space and auto-remediation thresholds before `2GB`.
5. Triage the `401` and `429` failures in `openclaw-agent`.
6. Keep Le Filon isolated on `46.225.173.203`; if any `lefilon*` containers or listeners reappear on `46.225.98.179`, treat that as configuration drift and remove them.
