#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?GitHub token is required}"
: "${GITHUB_REPOSITORY:?Repository is required}"
: "${GITHUB_ACTOR:?Actor is required}"
: "${DEFAULT_BRANCH:?Default branch is required}"
: "${IMAGE_DIGEST:?Image digest is required}"
: "${SOURCE_SHA:?Source SHA is required}"
test "${ENABLED:-}" = true || { echo "Real deployment is not enabled." >&2; exit 1; }
[[ "$GITHUB_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
[[ "$DEFAULT_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]]
[[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]

protected=$(gh api "repos/$GITHUB_REPOSITORY/environments/real-prod" \
  --jq '(.can_admins_bypass == false) and (.deployment_branch_policy.protected_branches == true) and ([.protection_rules[] | select(.type == "required_reviewers" and .prevent_self_review == true and (.reviewers | length) > 0)] | length > 0)')
test "$protected" = true || { echo "real-prod protection is missing." >&2; exit 1; }

image="ghcr.io/${GITHUB_REPOSITORY,,}@$IMAGE_DIGEST"
name=nodejs-demo-app
previous=nodejs-demo-app-previous
workdir=$(mktemp -d)
export DOCKER_CONFIG="$workdir"
previous_renamed=false
promoted=false

cleanup() {
  status=$?
  if [ "$promoted" != true ]; then
    if [ -s "$workdir/candidate.id" ]; then
      candidate=$(cat "$workdir/candidate.id")
      if [[ "$candidate" =~ ^[0-9a-f]{12,64}$ ]]; then
        docker rm -f "$candidate" || { echo "Could not remove failed candidate." >&2; status=1; }
      else
        echo "Invalid candidate ID; manual cleanup is required." >&2
        status=1
      fi
    fi
    if [ "$previous_renamed" = true ]; then
      docker start "$previous" >/dev/null || { echo "Could not restart previous container." >&2; status=1; }
      docker rename "$previous" "$name" || { echo "Could not restore previous container name." >&2; status=1; }
    fi
  fi
  rm -f "$workdir/config.json" "$workdir/candidate.id"
  rmdir "$workdir" || { echo "Could not remove temporary Docker configuration." >&2; status=1; }
  exit "$status"
}
trap cleanup EXIT

printf '%s' "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin >/dev/null
gh attestation verify "oci://$image" --repo "$GITHUB_REPOSITORY" \
  --signer-workflow "$GITHUB_REPOSITORY/.github/workflows/publish-image.yml" \
  --source-ref "refs/heads/$DEFAULT_BRANCH" --source-digest "$SOURCE_SHA" \
  --deny-self-hosted-runners
docker pull "$image"

names=$(docker container ls -a --format '{{.Names}}')
if printf '%s\n' "$names" | grep -Fxq "$previous"; then
  echo "Previous deployment container exists; resolve it manually." >&2
  exit 1
fi
if printf '%s\n' "$names" | grep -Fxq "$name"; then
  owner=$(docker inspect --format '{{ index .Config.Labels "demo.repository" }}' "$name")
  running=$(docker inspect --format '{{.State.Running}}' "$name")
  test "$owner" = "$GITHUB_REPOSITORY" && test "$running" = true || {
    echo "Existing container is not a running container managed by this repository." >&2
    exit 1
  }
  docker rename "$name" "$previous"
  previous_renamed=true
  docker stop "$previous" >/dev/null
fi

docker run -d --cidfile "$workdir/candidate.id" --name "$name" \
  --label "demo.repository=$GITHUB_REPOSITORY" \
  --restart unless-stopped --publish 127.0.0.1:3000:3000 "$image" >/dev/null
healthy=false
for attempt in $(seq 1 10); do
  if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:3000/ >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
test "$healthy" = true || { echo "Smoke test failed; restoring the previous container." >&2; exit 1; }
promoted=true
if [ "$previous_renamed" = true ]; then
  docker rm "$previous" >/dev/null || { echo "New container is running; remove the previous container manually." >&2; exit 1; }
fi
echo "Deployed $image from source $SOURCE_SHA."
