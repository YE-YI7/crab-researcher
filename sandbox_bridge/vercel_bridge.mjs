import { createInterface } from 'node:readline';
import { readFile } from 'node:fs/promises';
import { Sandbox } from '@vercel/sandbox';

let sandbox = null;
const runnerPath = new URL('./runner.py', import.meta.url);

function reply(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function errorMessage(error) {
  const detail = error?.json?.error?.message || error?.json?.message || error?.text;
  return [error?.message || String(error), detail]
    .filter(Boolean)
    .join(': ')
    .slice(0, 2000);
}

function allowedTargets(domains) {
  return [...new Set(domains.flatMap(domain => [domain, `*.${domain}`]))];
}

async function sandboxRequest(payload) {
  const encoded = Buffer.from(JSON.stringify(payload)).toString('base64');
  const client = [
    'import base64,json,sys,urllib.request',
    'data=base64.b64decode(sys.argv[1])',
    "request=urllib.request.Request('http://127.0.0.1:4765',data=data,headers={'Content-Type':'application/json'})",
    'print(urllib.request.urlopen(request,timeout=120).read().decode())',
  ].join(';');
  const result = await sandbox.runCommand('python3', ['-c', client, encoded]);
  if (result.exitCode !== 0) throw new Error((await result.stderr()).slice(0, 2000));
  return JSON.parse((await result.stdout()).trim());
}

async function start(message) {
  if (!process.env.VERCEL_SANDBOX_IMAGE) throw new Error('VERCEL_SANDBOX_IMAGE is required');
  const credentials = process.env.VERCEL_TOKEN ? {
    token: process.env.VERCEL_TOKEN,
    teamId: process.env.VERCEL_TEAM_ID,
    projectId: process.env.VERCEL_PROJECT_ID,
  } : {};
  sandbox = await Sandbox.create({
    image: process.env.VERCEL_SANDBOX_IMAGE,
    timeout: message.timeoutMs,
    resources: { vcpus: message.vcpus || 1 },
    persistent: false,
    networkPolicy: {
      allow: allowedTargets(message.allowedDomains),
    },
    ...credentials,
  });
  await sandbox.writeFiles([{ path: '/vercel/sandbox/runner.py', content: await readFile(runnerPath) }]);
  await sandbox.runCommand({
    cmd: 'python3',
    args: ['/vercel/sandbox/runner.py'],
    detached: true,
  });
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const result = await sandbox.runCommand('python3', ['-c', "import urllib.request;urllib.request.urlopen('http://127.0.0.1:4765',timeout=2).read()"]);
      if (result.exitCode === 0) return { sandboxId: sandbox.name };
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error('Browser RPC did not become ready inside the sandbox');
}

async function close() {
  if (sandbox) await sandbox.stop();
  sandbox = null;
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  try {
    const message = JSON.parse(line);
    if (message.type === 'start') reply({ ok: true, ...(await start(message)) });
    else if (message.type === 'execute') {
      if (!sandbox) throw new Error('Sandbox has not started');
      reply(await sandboxRequest(message));
    } else if (message.type === 'close') {
      await close();
      reply({ ok: true });
      break;
    } else throw new Error('Unknown bridge command');
  } catch (error) {
    reply({ ok: false, error: errorMessage(error) });
  }
}

await close().catch(() => {});
