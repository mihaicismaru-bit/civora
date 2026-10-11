# PARTENER.EU Romanian NAS runner

This project moves only the MIPE acquisition job to the Romanian Synology NAS.
The downstream PARTENER engine and persistence jobs continue on GitHub-hosted
runners and consume the immutable acquisition artifact.

## Security boundary

- Repository-scoped runner with the dedicated `romania-nas` label.
- No NAS shared folders and no Docker socket are mounted.
- The container is not privileged and exposes no listening ports.
- The acquisition workflow accepts only `schedule`, `workflow_dispatch`, and
  selected pushes to `main`; it does not run for pull requests.
- The one-hour GitHub registration token is needed only for first registration.
- GitHub Actions must require approval for all outside collaborators because the
  repository is public.

## Runtime

- Synology DS220+ (`linux/amd64`) with Container Manager.
- Microsoft Playwright Python `v1.61.0-noble` image.
- GitHub Actions runner `2.337.0`, verified with its published SHA-256 digest.
- One Chromium page at a time, images/media/fonts blocked by the crawler.
- Container limits: 1.25 CPU, 1152 MiB RAM, 256 MiB shared memory.

The Compose project is deployed under `/volume1/docker/civora-romania-runner`.
The runner work directory and credentials stay in the `runner_state` named
volume. No crawler result is canonical until the downstream engine validates
the handoff and persists it.
