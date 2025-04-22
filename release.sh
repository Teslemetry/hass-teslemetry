TARGET="2025.4.0"

git fetch upstream $TARGET
git rebase upstream/$TARGET

for BRANCH in $(gh pr list --repo home-assistant/core --author Bre77 --state open --json headRefName --jq '.[].headRefName'); do
  echo "Merging branch $BRANCH from fork"
  git fetch fork $BRANCH
  git merge --squash fork/$BRANCH
  git mergetool
done
