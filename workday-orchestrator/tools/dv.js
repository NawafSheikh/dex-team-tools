#!/usr/bin/env node
'use strict';
// dv: Dataverse / Power Platform REST helper for workday agents. Use a demo or sandbox environment.
// Usage:
//   dv login                                    one-time device-code sign-in, fills the token cache
//   dv token [dataverse|powerapps|flow|graph]   print a short-lived access token
//   dv GET  /api/data/v9.2/WhoAmI               call the Dataverse Web API
//   dv POST /api/data/v9.2/<path> '<json>'      body as an argument, or "-" to read stdin
//   dv PATCH|DELETE|PUT ...
//   dv flow GET|POST <url-or-path> [body]       call the Flow service (api.flow.microsoft.com)
//   Extra request headers: DV_HEADERS='MSCRM.SolutionUniqueName: MySolution; Prefer: return=representation'
// Prints the HTTP status on stderr and the response body on stdout. Exit 1 on HTTP >= 400.
const fs = require('fs');
const path = require('path');
const { PublicClientApplication } = require('@azure/msal-node');

// Settings (see ../.env.example). DV_CACHE is an MSAL token cache written by a one-time interactive sign-in;
// workers only ever call this helper, they never read the cache themselves.
const CACHE = process.env.DV_CACHE || path.join(process.env.HOME || process.env.USERPROFILE || '.', '.dv-msal.json');
const ORG = (process.env.DV_ORG || '').replace(/\/$/, '');  // e.g. https://<org>.crm.dynamics.com
const ENV_ID = process.env.DV_ENV_ID || '';                 // Power Platform environment id
// Microsoft's public first-party client id for the Azure CLI, a public client usable for delegated sign-in.
const CLIENT_ID = process.env.DV_CLIENT_ID || '04b07795-8ddb-461a-bbee-02f9e1bf7b46';
function requireSettings() {
  if (!ORG || !ENV_ID) throw new Error('set DV_ORG and DV_ENV_ID');
}
const SCOPES = {
  dataverse: `${ORG}/.default`,
  powerapps: 'https://service.powerapps.com/.default',
  flow: 'https://service.flow.microsoft.com/.default',
  graph: 'https://graph.microsoft.com/.default',  // read-only checks (e.g. the account's licences)
};

function cachePlugin(file) {
  return {
    beforeCacheAccess: async (ctx) => {
      if (fs.existsSync(file)) ctx.tokenCache.deserialize(fs.readFileSync(file, 'utf8'));
    },
    afterCacheAccess: async (ctx) => {
      if (ctx.cacheHasChanged) fs.writeFileSync(file, ctx.tokenCache.serialize(), { mode: 0o600 });
    },
  };
}

function client() {
  return new PublicClientApplication({
    auth: { clientId: CLIENT_ID, authority: 'https://login.microsoftonline.com/organizations' },
    cache: { cachePlugin: cachePlugin(CACHE) },
  });
}

// One-time interactive sign-in (device code). The person signs in in their own browser; no password passes here.
async function login() {
  requireSettings();
  const res = await client().acquireTokenByDeviceCode({
    scopes: [SCOPES.dataverse],
    deviceCodeCallback: (r) => process.stderr.write(`${r.message}
`),
  });
  process.stderr.write(`signed in as ${res.account.username}; token cache at ${CACHE}
`);
  return 0;
}

async function token(kind) {
  requireSettings();
  const scope = SCOPES[kind];
  if (!scope) throw new Error(`unknown token kind ${kind}`);
  const pca = client();
  const [account] = await pca.getTokenCache().getAllAccounts();
  if (!account) throw new Error('no signed-in account in the token cache');
  const res = await pca.acquireTokenSilent({ account, scopes: [scope] });
  return res.accessToken;
}

function readBody(arg) {
  if (arg === undefined) return undefined;
  return arg === '-' ? fs.readFileSync(0, 'utf8') : arg;
}

async function call(kind, method, target, bodyArg) {
  const base = kind === 'flow' ? 'https://api.flow.microsoft.com' : ORG;
  let url = target.startsWith('http') ? target : `${base}${target.startsWith('/') ? '' : '/'}${target}`;
  url = url.replace('{env}', ENV_ID);
  if (kind === 'flow' && !/api-version=/.test(url)) url += `${url.includes('?') ? '&' : '?'}api-version=2016-11-01`;
  const headers = {
    Authorization: `Bearer ${await token(kind)}`,
    Accept: 'application/json',
    'OData-MaxVersion': '4.0',
    'OData-Version': '4.0',
  };
  const body = readBody(bodyArg);
  if (body !== undefined) headers['Content-Type'] = 'application/json; charset=utf-8';
  if (method !== 'GET') headers.Prefer = 'return=representation';
  for (const pair of (process.env.DV_HEADERS || '').split(';').map((x) => x.trim()).filter(Boolean)) {
    const i = pair.indexOf(':');
    if (i > 0) headers[pair.slice(0, i).trim()] = pair.slice(i + 1).trim();
  }
  const res = await fetch(url, { method, headers, body });
  const text = await res.text();
  process.stderr.write(`HTTP ${res.status}${res.headers.get('OData-EntityId') ? ` ${res.headers.get('OData-EntityId')}` : ''}\n`);
  process.stdout.write(text ? `${text}\n` : '');
  return res.status < 400 ? 0 : 1;
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd || cmd === '-h' || cmd === '--help') {
    process.stdout.write(fs.readFileSync(__filename, 'utf8').split('\n').slice(2, 12).join('\n') + '\n');
    return 0;
  }
  if (cmd === 'login') return login();
  if (cmd === 'token') {
    process.stdout.write(`${await token(rest[0] || 'dataverse')}\n`);
    return 0;
  }
  if (cmd === 'flow') return call('flow', rest[0].toUpperCase(), rest[1], rest[2]);
  return call('dataverse', cmd.toUpperCase(), rest[0], rest[1]);
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stderr.write(`dv failed: ${e.errorCode || ''} ${e.message}\n`);
  process.exit(2);
});
