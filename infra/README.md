# Operations

## Local stack

1. Copy the examples and choose strong unique values:

   ```powershell
   Copy-Item .env.example .env
   Copy-Item backend/.env.example backend/.env
   ```

2. In `backend/.env`, retain the application secrets. In the root `.env`, set a
   strong `LITELLM_MASTER_KEY` and the `OPENROUTER_API_KEY` and `NVIDIA_API_KEY` consumed only by the
   LiteLLM service. The Compose stack overrides `DATABASE_URL`, the Deep Agents
   checkpoint database, and `LITELLM_BASE_URL` for its internal services.
3. Start the stack from the repository root:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

The API is available through Caddy at `http://localhost:8080/health`. Data
services deliberately have no host port bindings. Use `docker compose exec`
for maintenance access, for example `docker compose exec postgres psql -U
learning_coach -d learning_coach`.

## Production follow-up

This is the local/staging foundation, not a production claim: pin images to
digests, switch Caddy to a real domain with HTTPS, use SOPS+age or Docker
secrets, add backup/restore jobs and offsite storage, and deploy gVisor or
Firecracker before permitting untrusted code execution.
