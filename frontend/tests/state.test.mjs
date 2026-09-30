import test from 'node:test';
import assert from 'node:assert/strict';
import {safeStoredArray, RequestOwnership, blendInputs, routeFromHash} from '../assets/state.mjs';

test('malformed stored preferences cannot stop startup', () => {
  assert.deepEqual(safeStoredArray('{broken'), []);
  assert.deepEqual(safeStoredArray('{"Drama":true}'), []);
  assert.deepEqual(safeStoredArray('["Drama",null,2,"Drama"]'), ['Drama']);
});
test('a newer search and session change reject older responses', () => {
  const owner = new RequestOwnership();
  const old = owner.begin('search');
  const current = owner.begin('search');
  assert.equal(old.signal.aborted, true);
  assert.equal(old.isCurrent(), false);
  assert.equal(current.isCurrent(), true);
  owner.resetSession();
  assert.equal(current.isCurrent(), false);
  assert.equal(current.signal.aborted, true);
});
test('country replacement cancels prior provider generation independently of search', () => {
  const owner = new RequestOwnership();
  const search = owner.begin('search');
  const providers = owner.begin('providers');
  owner.begin('providers');
  assert.equal(providers.isCurrent(), false);
  assert.equal(search.isCurrent(), true);
});
test('hybrid sends only visible inputs and honest effective complementary weights', () => {
  assert.deepEqual(blendInputs([], ['Drama'], .7), {movie_ids: [], genres:['Drama'], weight_content:0, weight_genre:1});
  assert.deepEqual(blendInputs([42], [], .7), {movie_ids:[42], genres:[], weight_content:1, weight_genre:0});
  const combined = blendInputs([42,42], ['Drama','Comedy'], .6);
  assert.equal(combined.weight_content + combined.weight_genre, 1);
  assert.deepEqual(combined.movie_ids, [42]);
  assert.throws(() => blendInputs([], [], .7), /Select/);
  assert.throws(() => blendInputs([42], ['Drama'], 0/0), /weight/);
});
test('public and owner list routes survive reload and exit to explore', () => {
  assert.deepEqual(routeFromHash('#list/abc123'), {page:'shared-list',slug:'abc123'});
  assert.deepEqual(routeFromHash('#my-list/8'), {page:'owner-list',id:8});
  assert.deepEqual(routeFromHash('#explore'), {page:'explore'});
  assert.deepEqual(routeFromHash('#bogus'), {page:'explore'});
});
