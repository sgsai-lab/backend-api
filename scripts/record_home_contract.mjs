// Records a contract fixture from the home API (sgsai-lab/home, ADR-002): the raw Firestore
// documents it stores and the JSON it returns. The Postgres spike must reproduce that JSON.
//
//   node scripts/record_home_contract.mjs ../home > tests/fixtures/home_contract.json
//
// Runs entirely in memory: no Firestore, SMTP or network.
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const home = path.resolve(process.argv[2] ?? '../home');
const load = (file) => import(pathToFileURL(path.join(home, file)).href);
const { createServer } = await load('src/server/server.mjs');
const db = await load('src/server/db.mjs');
const { hashPassword } = await load('src/server/security.mjs');

db.setFirestoreDisabled(true);
const server = createServer({ env: {}, sendEmail: async () => {}, limiters: Object.fromEntries(['auth', 'authEmail', 'mfa', 'mutations', 'invites', 'uploads', 'launch'].map((name) => [name, () => true])) });
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const call = async (pathname, { method = 'GET', body, token } = {}) => {
  const response = await fetch(`${base}${pathname}`, {
    method,
    headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  return response.json();
};
async function account(email, role) {
  await db.saveUser({ ...db.newUser({ email, name: email.split('@')[0], provider: 'password', emailVerified: true, role }), password_hash: await hashPassword('correct horse battery') });
  return (await call('/api/v1/auth/login', { method: 'POST', body: { email, password: 'correct horse battery' } })).access_token;
}

const admin = await account('admin@sgs.test', 'admin');
const lead = await account('lead@riverside.example', 'user');
const client = await call('/api/v1/clients', { method: 'POST', token: admin, body: { name: 'Riverside Academy', primary_sector: 'education', contact: { email: 'office@riverside.example' }, branding: { primary_color: '#3355ff' } } });
await call(`/api/v1/clients/${client.id}/members`, { method: 'POST', token: admin, body: { email: 'lead@riverside.example', role: 'admin' } });
const project = await call('/api/v1/projects', { method: 'POST', token: lead, body: { client_id: client.id, name: 'Learning portal', summary: 'Year 9 PWA', status: 'in_progress', tags: ['lms', 'pilot'], start_date: '2026-09-01', end_date: '2027-07-15', sector_profile: { institution_type: 'school', programme: 'Year 9 science', academic_year: '2026/27' }, use_template: true } });
const product = await call('/api/v1/products', { method: 'POST', token: admin, body: { client_id: client.id, project_id: project.id, kind: 'pwa', name: 'Learning Portal', summary: 'Courses and homework', launch_url: 'https://learn.riverside.example/app', status: 'live', visibility: 'client', order: 1 } });

const collections = {};
for (const name of ['users', 'clients', 'memberships', 'projects', 'products']) {
  collections[name] = (await db.queryDocs(name)).map(({ password_hash: _hash, ...doc }) => doc);
}
const responses = {
  client: await call(`/api/v1/clients/${client.id}`, { token: lead }),
  project: await call(`/api/v1/projects/${project.id}`, { token: lead }),
  products: await call(`/api/v1/products?client_id=${client.id}`, { token: lead })
};
server.close();
process.stdout.write(`${JSON.stringify({ recorded_from: 'sgsai-lab/home in-memory API', viewer_role: 'admin', collections, responses }, null, 2)}\n`);
