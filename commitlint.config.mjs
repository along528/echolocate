// Conventional Commits enforcement (see CONTRIBUTING.md and CLAUDE.md).
// Every commit in a PR is linted against this config by the `commitlint` CI check.
// The subject line drives semantic-release version bumps on merge to main:
//   feat: -> minor, fix: -> patch, BREAKING CHANGE (footer) -> major.
//
// ESM (.mjs) is required: wagoid/commitlint-github-action@v6 rejects a .js configFile.
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // Allow the scopes used across this monorepo (empty scope is also fine).
    'scope-enum': [
      1,
      'always',
      ['vector-rs', 'sonar', 'mcp', 'embeddings', 'finetune', 'echoes', 'ci', 'deps', 'release'],
    ],
  },
};
