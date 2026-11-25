// Money is calculated in tenths of a million to avoid floating-point drift.
export const money = (value) => Math.round(value * 10) / 10;

export function squadValue(team, prices) {
  return money([...team.players, ...team.bench].reduce((sum, id) => sum + prices[id], 0));
}

export function spendingLimit(team, prices, startingBudget = 60) {
  return team ? money(squadValue(team, prices) + team.bank) : startingBudget;
}

// Older squads did not record cash. Reconstruct it from their gameweek
// selections and the published review history. Reviews after GW3 first apply
// to GW4. Historical transaction times were not stored, so this is a fallback.
export function restoreBanks(teams, priceState, startingBudget = 60) {
  let previous = null;
  return [...teams].sort((a, b) => a.gameweek - b.gameweek).map((team) => {
    let bank = team.bank;
    if (!Number.isFinite(bank)) {
      const prices = Object.fromEntries(Object.entries(priceState.prices).map(([id, price]) => [
        id,
        money(price - (priceState.reviewsById[id] || [])
          .filter((review) => review.throughGameweek >= team.gameweek)
          .reduce((total, review) => total + review.move, 0))
      ]));
      // Keep previously accepted legacy squads valid without granting more
      // cash when their old spending exceeded the reconstructed allowance.
      bank = Math.max(0, money(spendingLimit(previous, prices, startingBudget) - squadValue(team, prices)));
    }
    previous = { ...team, bank };
    return previous;
  });
}
