#!/usr/bin/env bash
# Fail-fast check of the repository Actions variables the CXAS jobs need.
#
# Inputs (env, from ${{ vars.* }}): WIF_PROVIDER, CI_SA, LIVE_APP_ID, STAGING_APP_ID.
# Outputs (appended to $GITHUB_ENV): GCP_PROJECT_ID, GCP_PROJECT_NUMBER,
# CXAS_LIVE_APP_ID, CXAS_STAGING_APP_ID, STAGING_APP_NAME.
# The project ID and number are masked (::add-mask::) so public logs show ***.
set -euo pipefail

missing=()
[[ -n "${WIF_PROVIDER:-}" ]] || missing+=(GCP_WIF_PROVIDER)
[[ -n "${CI_SA:-}" ]] || missing+=(GCP_CI_SERVICE_ACCOUNT)
[[ -n "${LIVE_APP_ID:-}" ]] || missing+=(CXAS_LIVE_APP_ID)
[[ -n "${STAGING_APP_ID:-}" ]] || missing+=(CXAS_STAGING_APP_ID)
if (( ${#missing[@]} )); then
  echo "::error title=Missing repo variables::Set ${missing[*]} under GitHub Settings -> Secrets and variables -> Actions -> Variables (see docs). Forked pull requests cannot read them."
  exit 1
fi

number="$(sed -n 's#^projects/\([0-9][0-9]*\)/locations/global/workloadIdentityPools/[^/][^/]*/providers/[^/][^/]*$#\1#p' <<<"${WIF_PROVIDER}")"
if [[ -z "${number}" ]]; then
  echo "::error title=Bad GCP_WIF_PROVIDER::expected projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>"
  exit 1
fi
if [[ ! "${CI_SA}" =~ ^[a-z][a-z0-9-]*@([a-z][a-z0-9-]*)\.iam\.gserviceaccount\.com$ ]]; then
  echo "::error title=Bad GCP_CI_SERVICE_ACCOUNT::expected <name>@<project>.iam.gserviceaccount.com"
  exit 1
fi
project="${BASH_REMATCH[1]}"
uuid_re='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
for pair in "CXAS_LIVE_APP_ID=${LIVE_APP_ID}" "CXAS_STAGING_APP_ID=${STAGING_APP_ID}"; do
  if [[ ! "${pair#*=}" =~ ${uuid_re} ]]; then
    echo "::error title=Bad ${pair%%=*}::expected an app UUID (the last part of projects/.../apps/<uuid>)"
    exit 1
  fi
done
if [[ "${LIVE_APP_ID}" == "${STAGING_APP_ID}" ]]; then
  echo "::error title=Bad app IDs::CXAS_LIVE_APP_ID and CXAS_STAGING_APP_ID must differ"
  exit 1
fi

echo "::add-mask::${project}"
echo "::add-mask::${number}"
location="${CXAS_LOCATION:-us}"
{
  echo "GCP_PROJECT_ID=${project}"
  echo "GCP_PROJECT_NUMBER=${number}"
  echo "CXAS_LIVE_APP_ID=${LIVE_APP_ID}"
  echo "CXAS_STAGING_APP_ID=${STAGING_APP_ID}"
  echo "STAGING_APP_NAME=projects/${project}/locations/${location}/apps/${STAGING_APP_ID}"
} >> "${GITHUB_ENV:?GITHUB_ENV not set}"
echo "Repo variables OK: WIF provider, CI service account, live + staging app IDs (location ${location})."
