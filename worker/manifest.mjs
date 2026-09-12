import schema from '../docs/manifest.schema.json' with { type: 'json' };
import { fail } from './index.mjs';
// The same schema subset as scripts/check-manifest.py; no runtime dependency.
export function validate(value, rule = schema, path = '$') {
  const bad = message => fail(400, `${path}: ${message}`);
  if (rule.$ref) validate(value, rule.$ref.slice(2).split('/').reduce((v, key) => v[key], schema), path);
  if (rule.oneOf) {
    const count = rule.oneOf.filter(option => { try { validate(value, option, path); return true; } catch { return false; } }).length;
    if (count !== 1) bad('must match exactly one entry shape');
  }
  if (rule.not) { let match = true; try { validate(value, rule.not, path); } catch { match = false; } if (match) bad('reserved value'); }
  const type = value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
  if (rule.type && !(rule.type === 'integer' ? Number.isSafeInteger(value) : rule.type === type)) bad(`expected ${rule.type}`);
  if ('const' in rule && value !== rule.const) bad('unexpected value');
  if (rule.enum && !rule.enum.includes(value)) bad('not an allowed value');
  if (type === 'object') {
    for (const key of rule.required || []) if (!(key in value)) bad(`missing ${key}`);
    for (const [key, item] of Object.entries(value)) {
      if (rule.additionalProperties === false && !Object.hasOwn(rule.properties || {}, key)) bad(`unknown property ${key}`);
      if (rule.properties?.[key]) validate(item, rule.properties[key], `${path}.${key}`);
    }
  }
  if (type === 'array') {
    if (value.length > (rule.maxItems ?? Infinity)) bad('too many items');
    if (rule.uniqueItems && new Set(value.map(item => JSON.stringify(item))).size !== value.length) bad('duplicate items');
    value.forEach((item, index) => validate(item, rule.items || {}, `${path}[${index}]`));
  }
  if (type === 'string') {
    if ([...value].length > (rule.maxLength ?? Infinity)) bad('too long');
    if ([...value].length < (rule.minLength || 0)) bad('must not be empty');
    if (rule.pattern && !new RegExp(rule.pattern).test(value)) bad('invalid format');
    if (rule.format === 'uri') { try { const url = new URL(value); if (!['http:', 'https:', 'file:'].includes(url.protocol) || /\s/.test(value)) bad('invalid URL'); } catch { bad('invalid URL'); } }
    if (rule.format === 'date' && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) bad('expected YYYY-MM-DD date');
  }
  if (typeof value === 'number' && (value < (rule.minimum ?? value) || value > (rule.maximum ?? value))) bad('out of range');
}
export function checkManifest(manifest) {
  validate(manifest);
  if (manifest.links?.video) {
    const url = new URL(manifest.links.video);
    if (url.hostname !== 'youtu.be' && (url.searchParams.getAll('v').length !== 1 || !/^[A-Za-z0-9_-]{11}$/.test(url.searchParams.get('v')))) fail(400, 'Use one YouTube video ID.');
  }
  if (manifest.release?.sha256 === 'pending') fail(400, 'A published release checksum is required.');
  if (manifest.selfcheck && manifest.entry === null) fail(400, 'A selfcheck needs a runnable entry.');
  if (manifest.health && !manifest.requires.ports.length) fail(400, 'A health check needs a declared port.');
  if (manifest.entry === null && !manifest.tags.includes('library')) fail(400, 'A null entry requires the library tag.');
}
