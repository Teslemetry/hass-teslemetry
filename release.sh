TARGET="2025.4.0"

git fetch upstream $TARGET
git rebase upstream/$TARGET

for PR in $(gh pr list --repo home-assistant/core --author Bre77 --state open --json number --jq '.[].number'); do
  echo "Applying patch from PR #$PR"
  curl -L https://github.com/home-assistant/core/pull/$PR.patch -o $PR.patch
  git apply -3 $PR.patch
  git mergetool
  rm *.patch
done
