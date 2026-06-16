import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { compareCore, verifyRelease } from './index.mjs';

const logger = { log() {} };

/**
 * Build a temp project dir with a fake `npm` on PATH.
 * @param {object} [opts] - options.
 * @param {string} [opts.latest] - version the fake `npm view` returns.
 * @param {boolean} [opts.fail] - make the fake `npm` exit non-zero.
 * @returns {{ dir: string, env: object }} temp dir and an env with the fake npm.
 */
function project({ latest, fail = false } = {}) {
    const dir = mkdtempSync(join(tmpdir(), 'guard-'));
    const bin = join(dir, 'bin');
    mkdirSync(bin);

    const body = fail
        ? 'process.exit(1)\n'
        : `if (process.argv[2] === 'view') process.stdout.write(${JSON.stringify(latest)})\n`;
    const npm = join(bin, 'npm');
    writeFileSync(npm, `#!/usr/bin/env node\n${body}`);
    chmodSync(npm, 0o755);

    writeFileSync(
        join(dir, 'package.json'),
        JSON.stringify({ name: '@scope/pkg', version: '0.0.0' }),
    );
    return { dir, env: { ...process.env, PATH: `${bin}:${process.env.PATH}` } };
}

/**
 * Run the guard against a temp project and report the outcome.
 * @param {string} version - the version semantic-release would publish.
 * @param {object} [setup] - {@link project} options.
 * @returns {Promise<string>} 'ALLOWED' or 'BLOCKED:<message>'.
 */
async function run(version, setup) {
    const { dir, env } = project(setup);
    const cwd = process.cwd();
    const path = process.env.PATH;
    process.chdir(dir);
    process.env.PATH = env.PATH;

    try {
        await verifyRelease({}, { nextRelease: { version }, logger, env });
        return 'ALLOWED';
    }
    catch (e) {
        return `BLOCKED:${e.message}`;
    }
    finally {
        process.chdir(cwd);
        process.env.PATH = path;
    }
}

test('compareCore orders versions', () => {
    assert.equal(compareCore('1.0.0', '3.20.1'), -1);
    assert.equal(compareCore('3.21.0', '3.20.1'), 1);
    assert.equal(compareCore('3.20.1', '3.20.1'), 0);
    assert.equal(compareCore('v3.20.2', '3.20.1'), 1);
});

test('blocks a major downgrade (1.0.0 over latest 3.20.1)', async () => {
    assert.match(await run('1.0.0', { latest: '3.20.1' }), /^BLOCKED:.*LOWER than the current npm/);
});

test('blocks a patch downgrade (3.20.0 over 3.20.1)', async () => {
    assert.match(await run('3.20.0', { latest: '3.20.1' }), /^BLOCKED:/);
});

test('allows an equal version', async () => {
    assert.equal(await run('3.20.1', { latest: '3.20.1' }), 'ALLOWED');
});

test('allows a forward version', async () => {
    assert.equal(await run('3.21.0', { latest: '3.20.1' }), 'ALLOWED');
});

test('skips (allows) when npm is unreachable', async () => {
    assert.equal(await run('1.0.0', { fail: true }), 'ALLOWED');
});
