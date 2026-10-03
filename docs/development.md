# Development workflow

Dayline uses [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow).
`main` holds completed, validated milestones. Use one short-lived branch and one
pull request per cohesive change. There is no separate `develop` branch.

The initial repository foundation is committed directly to `main`. Subsequent
implementation follows the branch and pull-request workflow below.

## Starting work

```sh
git switch main
git pull --ff-only
git switch -c feat/account-access
```

Choose a descriptive branch name: `feat/account-access`, `fix/reminder-timezone`,
or `docs/account-setup`. Follow the dependency order in [the roadmap](roadmap.md).
If a milestone needs several pull requests, each must leave the project coherent.

## Completing a change

1. Implement the selected milestone and its meaningful regression protection.
2. Run the applicable project checks and the focused verification listed in the
   roadmap. For documentation-only changes, check whitespace and local links.
3. Update affected documentation and the milestone checklist when its acceptance
   checks have passed. Record unverified account-dependent checks explicitly.
4. Review the diff, stage named files, and make a focused commit. Use descriptive
   messages such as `feat: add Microsoft account sign-in` or
   `fix: suppress reminders for completed tasks`.
5. Push the branch and open a pull request with the problem, resulting behavior,
   validation results, and any concrete limitation.
6. Merge with squash after validation and review; GitHub deletes the remote
   branch after merging. Update the local `main` before starting the next change.

```sh
git diff --check
git diff
git add <changed-files>
git commit -m "feat: add Microsoft account sign-in"
git push -u origin feat/account-access
gh pr create
```

The GitHub repository enables squash merging and automatic branch deletion.
Branches and pull requests are a documented workflow, not a claim that branch
protection or required checks already enforce it. Do not force-push `main`.
Use a new fix commit or revert to correct published changes.

## Validation and local data

There is no application test suite or CI workflow yet. Add the package, focused
tests, and CI checks with the first code milestone, then document their exact
commands here. CI must run using synthetic data without Microsoft credentials;
real-account checks are separate and their outcomes must be reported.

Keep maintained tests in `tests/` and durable documentation in `docs/`. Keep
one-off probes, temporary output, and local work notes in the ignored `.scratch/`
directory. The versioned roadmap is the user-requested implementation plan;
temporary investigation notes remain ignored.

Keep tokens, account data, and calendar URLs outside Git. The application will
store runtime data in XDG user directories and protect authentication persistence
with the desktop Secret Service. Local Git identity, credentials, and signing
settings belong to Git configuration, not committed project files.
