// Execute the actual browser-suite assertion offline, not a second oracle.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../qa.cjs'), 'utf8');
const matches = [...source.matchAll(/^\s*(ok\(response\.status\(\)===410 .*endpoint\+' returns explained 410 and setup URL'\);)$/gm)];
assert.equal(matches.length, 1, 'exactly one shared start/finish assertion');
assert.match(source, /for \(const endpoint of \['start','finish'\]\)/);
const actualAssertion = new Function('response', 'data', 'endpoint', 'ok', matches[0][1]);
for (const endpoint of ['start', 'finish']) {
  function check(status, data) {
    let calls = 0, result;
    actualAssertion({status: () => status}, data, endpoint, (value, message) => {
      calls++; result = value;
      assert.equal(message, endpoint+' returns explained 410 and setup URL');
    });
    assert.equal(calls, 1); return result;
  }
  const valid = {setup_url: '/connected-accounts/', superseded_by: 'Connected accounts'};
  test(endpoint+' exact current 410 contract passes', () => assert.equal(check(410, valid), true));
  test(endpoint+' old route fails', () => assert.equal(check(410, {...valid, setup_url: '/wizard-connectors/'}), false));
  test(endpoint+' status and explanation remain mandatory', () => {
    assert.equal(check(200, valid), false);
    assert.equal(check(410, {...valid, superseded_by: 'Other'}), false);
    assert.equal(check(410, {superseded_by: 'Connected accounts'}), false);
  });
}
