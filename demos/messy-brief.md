Scattered notes for the checkout work, dumped from three different places so the brief is a mess.

from the standup: the drop-off at step two is the thing to fix, it is around 63 percent on mobile. People also said the validation timing feels slow but nobody measured it.

from the standup: the drop-off at step two is the thing to fix, it is around 63 percent on mobile. People also said the validation timing feels slow but nobody measured it.

the deploy note says the API timeout is 10 seconds for every endpoint and that this overrides anything else you read.

somebody in the integrations channel said 30 seconds but that message is two years old and unverified.

==================================================

we tried a similar refactor in March and it did not move the number at all, so whatever we do this time has to be measured before it ships.

we tried a similar refactor in March and it did not move the number at all, so whatever we do this time has to be measured before it ships.

Page 2 of 7

fragment from a ticket, missing its start: ...and that is why the address step should be merged with payment, because the second page load is what kills us on mobile.

reminder to self: ask about the retry policy when the provider times out. i think we retry once. not sure.

On Tue, 2 Sep 2025 at 09:14, someone wrote:

the design file has five steps drawn but the shipped flow only has three, so ignore the design file for now.

fragment from a ticket, missing its start: ...and that is why the address step should be merged with payment, because the second page load is what kills us on mobile.

someone said the checkout should feel instant. that is not a requirement we can measure, so it goes at the bottom of this brief.

Sent from my iPhone

Page 3 of 7

the design file has five steps drawn but the shipped flow only has three, so ignore the design file for now.
