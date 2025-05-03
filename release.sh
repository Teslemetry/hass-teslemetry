# Get everything up to date
git checkout main
git fetch upstream dev
git rebase upstream/dev
git push --force-with-lease

# Ask for version
echo "Enter the target version:"
read VERSION

git branch -D release-$VERSION
git checkout -b release-$VERSION

rm release_notes.txt

for PR_NUMBER in $(gh pr list --repo home-assistant/core --author Bre77 --state open --json number | jq -r '.[].number'); do
    PR_TITLE=$(gh pr view $PR_NUMBER --repo home-assistant/core --json title | jq -r '.title')
    echo "Applying patch from PR #$PR_NUMBER: $PR_TITLE"
    curl -L https://github.com/home-assistant/core/pull/$PR_NUMBER.patch -o $PR_NUMBER.patch
    git apply -3 $PR_NUMBER.patch
    git mergetool
    rm *.patch
    git commit -am "#$PR_NUMBER: $PR_TITLE" --no-verify
    echo "[#$PR_NUMBER](https://github.com/home-assistant/core/pull/$PR_NUMBER): $PR_TITLE" >> release_notes.txt
done

yq -i -o json ".version=\"$VERSION\"" "homeassistant/components/teslemetry/manifest.json"
echo "" >> release_notes.txt
echo "**Full Changelog**: https://github.com/Teslemetry/hass-teslemetry/commits/v$VERSION" >> release_notes.txt

git commit -am "v$VERSION" --no-verify

script/setup
uv pip install -r requirements_test_all.txt
pytest tests/components/teslemetry

read -p "Press Enter to release..."

git tag -a v$VERSION -m "Release $VERSION"
git push origin v$VERSION
cd homeassistant/components
zip -r ../../teslemetry.zip teslemetry
cd ../..
gh release create v$VERSION -p -F release_notes.txt --repo Teslemetry/hass-teslemetry -t "Beta v$VERSION"
gh release upload v$VERSION teslemetry.zip --repo Teslemetry/hass-teslemetry
rm teslemetry.zip
git push
git checkout main
