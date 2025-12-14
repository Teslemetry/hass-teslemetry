# Get everything up to date
git checkout main
git fetch upstream dev
git rebase upstream/dev
git push --force-with-lease

# Ask for version
echo "Last version:"
gh release ls --repo teslemetry/hass-teslemetry --limit 1
echo "New version:"
read VERSION

git branch -D release-$VERSION
git checkout -b release-$VERSION

rm release_notes.txt

for PR_NUMBER in $(gh pr list --repo home-assistant/core --author Bre77 --state open --json number | jq -r '.[].number'); do
    PR_TITLE=$(gh pr view $PR_NUMBER --repo home-assistant/core --json title | jq -r '.title')
    echo "Applying patch from PR #$PR_NUMBER: $PR_TITLE"
    gh pr diff $PR_NUMBER --patch --repo home-assistant/core | git apply -3
    git mergetool
    git commit -am "#$PR_NUMBER: $PR_TITLE" --no-verify
    echo "[#$PR_NUMBER](https://github.com/home-assistant/core/pull/$PR_NUMBER): $PR_TITLE" >> release_notes.txt
done

cp "homeassistant/components/teslemetry/manifest.json" "custom_components/teslemetry/manifest.json"
yq -i -o json ".version=\"$VERSION\"" "custom_components/teslemetry/manifest.json"
yq -i -o json ".issue_tracker=\"https://github.com/Teslemetry/hass-teslemetry/issues\"" "custom_components/teslemetry/manifest.json"
echo "" >> release_notes.txt
echo "**Full Changelog**: https://github.com/Teslemetry/hass-teslemetry/commits/v$VERSION" >> release_notes.txt

git commit -am "v$VERSION" --no-verify

source .venv/bin/activate
script/setup
uv pip install -r requirements_test_all.txt
pytest tests/components/teslemetry
deactivate

read -p "Press Enter to release..."

git tag -a v$VERSION -m "Release $VERSION"
git push origin v$VERSION
cd homeassistant/components/teslemetry
rm -r __pycache__
rm *.orig
zip -r ../../../teslemetry.zip *
cd ../../..
gh release create v$VERSION -F release_notes.txt --repo Teslemetry/hass-teslemetry -t "Beta v$VERSION"
gh release upload v$VERSION teslemetry.zip --repo Teslemetry/hass-teslemetry
rm teslemetry.zip
git push --set-upstream origin release-$VERSION


git checkout main
git restore .
