# Deployment configuration

Set `CONTAINER_REGISTRY` to the self-hosted registry hostname and add
`REGISTRY_USERNAME` / `REGISTRY_PASSWORD` secrets with push access. The target
hosts need `/opt/learning-coach/backend/docker-compose.deploy.yml`, a protected
`.env`, and registry pull access. Add the matching `*_DEPLOY_HOST`,
`*_DEPLOY_USER`, and `*_DEPLOY_SSH_KEY` secrets. Configure the GitHub
`production` Environment with required reviewers before releasing a `v*` tag.

To roll back, redeploy a previously recorded immutable digest with
`IMAGE=<digest> docker compose -f docker-compose.deploy.yml up -d --wait`.
