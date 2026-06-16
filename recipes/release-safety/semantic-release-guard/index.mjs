/**
 * @cyberskill/semantic-release-guard
 *
 * A semantic-release plugin that runs in the `verifyRelease` phase (after the
 * version is computed, before `prepare`/`publish`). It aborts the release if
 * the version semantic-release wants to publish is LOWER than the package's
 * current `latest` dist-tag on the npm registry.
 *
 * Why it exists
 * -------------
 * semantic-release derives "the current version" entirely from git tags, not
 * from package.json. If a repository is moved or its history rebuilt without
 * its version tags, semantic-release has no baseline, defaults to 1.0.0, and
 * silently publishes *backwards* over a higher published version — stealing the
 * `latest` dist-tag. This plugin turns that into a hard, self-explaining
 * failure instead of a quiet downgrade.
 *
 * Add it to release.config.js BEFORE @semantic-release/npm:
 *
 *   plugins: [
 *     '@semantic-release/commit-analyzer',
 *     '@semantic-release/release-notes-generator',
 *     '@cyberskill/semantic-release-guard',   // <-- gate
 *     '@semantic-release/npm',
 *     '@semantic-release/github',
 *   ]
 *
 * REQUIRED: the CI checkout must use `fetch-depth: 0` so semantic-release (and
 * this guard) can see the full history and all tags. A shallow clone hides the
 * tags and is what makes the downgrade happen in the first place.
 *
 * Intentionally dependency-free (no `semver` import) so it resolves cleanly
 * under pnpm's strict node_modules.
 */

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * Compare two `major.minor.patch` versions. A leading `v` and any prerelease
 * suffix are ignored — the release branch only produces stable versions.
 * @param {string} a - first version.
 * @param {string} b - second version.
 * @returns {number} 1 if a > b, -1 if a < b, 0 if equal.
 */
export function compareCore(a, b) {
    const parse = (v) => v.replace(/^v/, '').split('-')[0].split('.').map(Number);
    const pa = parse(a);
    const pb = parse(b);

    for (let i = 0; i < 3; i++) {
        const x = pa[i] || 0;
        const y = pb[i] || 0;
        if (x > y) return 1;
        if (x < y) return -1;
    }

    return 0;
}

/**
 * semantic-release `verifyRelease` hook. Aborts if the computed version is
 * lower than npm's current `latest`.
 * @param {object} _pluginConfig - semantic-release plugin config (unused).
 * @param {object} context - semantic-release context.
 * @param {object} context.nextRelease - the release semantic-release computed.
 * @param {object} context.logger - semantic-release logger.
 * @param {object} context.env - environment for child processes (npm config/auth).
 */
export async function verifyRelease(_pluginConfig, { nextRelease, logger, env }) {
    const next = nextRelease && nextRelease.version;
    if (!next) return;

    const pkg = JSON.parse(readFileSync(resolve('package.json'), 'utf-8'));
    const name = pkg.name;

    let latest = '';
    try {
        latest = execFileSync('npm', ['view', name, 'dist-tags.latest'], {
            encoding: 'utf-8',
            env,
            stdio: ['ignore', 'pipe', 'pipe'],
        }).trim();
    }
    catch {
        // Unpublished package, private, or a transient registry error. The guard
        // is a safety net, not a hard gate — never block a legitimate release
        // because npm was momentarily unreachable.
        logger.log(
            `Downgrade guard: could not read "latest" for ${name} from npm `
            + '(unpublished or registry error) — skipping.',
        );
        return;
    }

    if (!latest) {
        logger.log('Downgrade guard: no existing "latest" on npm — skipping.');
        return;
    }

    if (compareCore(next, latest) < 0) {
        const msg
            = `Release blocked: computed version ${next} is LOWER than the current `
            + `npm "latest" ${latest}. This almost always means the git version `
            + 'tags are missing and semantic-release lost its baseline. Restore the '
            + 'tags (e.g. `git push origin --tags`) before releasing.';
        // GitHub Actions annotation (read from stdout; avoids the no-console rule).
        process.stdout.write(`::error title=Version regression blocked::${msg}\n`);
        throw new Error(msg);
    }

    logger.log(`Downgrade guard OK: ${next} >= current latest ${latest}.`);
}
