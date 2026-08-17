// Journey Builder console script — generated 2026-08-17 20:22 UTC
// Journey: JBCL | PROMO | promotion campaign (cloned from JRN-0-600001)
// Target: any deployment speaking /journey-builder/v0 (this sandbox by default)
//
// HOW TO RUN:
//   1. Open the Journey Builder UI in Chrome, logged in if the target needs it.
//   2. F12 -> Console tab (if Chrome warns, type: allow pasting).
//   3. Paste this whole script and press Enter.
//   4. Wait for "DONE" with the created JRN ids.
//
// Internal ids in the payload below are freshly minted for this download;
// promotion display ids are blank so the server re-mints them. Paste the
// same file twice and the second run simply creates another copy.
(async () => {
  'use strict';
  // Optional: paste an access token here when the target requires auth.
  const MANUAL_TOKEN = '';
  const BASE = location.origin + '/api/v0/crm/journey-builder/v0';
  const PUBLISH = true;   // false -> leave the created journey as Draft

  const PAYLOADS = [
    {
      "journeyName": "JBCL | PROMO | promotion campaign",
      "brand": "JBCL",
      "currencyCodes": [
        "CLP"
      ],
      "timeZoneId": "Chile/Continental",
      "isImmediatelyAfterPublish": true,
      "isUnlimited": true,
      "reEntryRule": {
        "reEntryMode": "Prohibited"
      },
      "activities": [
        {
          "activityId": "2d499732-04e3-4f8d-b394-2ad77b336a08",
          "activityName": "external_system_source",
          "activityDisplayName": "API entry",
          "events": [
            {
              "eventName": "PlayerAdded",
              "eventType": "Activation",
              "nextActivityId": "25ba9554-20a9-46e5-9fc6-44f11dd9d84a"
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "targetSystem": "Randomizer",
            "description": "Promo page / randomizer prize routes players here"
          }
        },
        {
          "activityId": "25ba9554-20a9-46e5-9fc6-44f11dd9d84a",
          "activityName": "promotion",
          "activityDisplayName": "Promotion offer",
          "events": [
            {
              "eventName": "PromotionAccepted",
              "eventType": "Completion",
              "nextActivityId": "37433fff-7660-4132-89b2-3ae2b0b4491c"
            },
            {
              "eventName": "PromotionExpired",
              "eventType": "Completion",
              "nextActivityId": "446fc9ec-73f1-43d5-a3ab-89034c9bd6c5"
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "autoAccept": false,
            "timeToAccept": "P0Y0M1DT0H0M0S",
            "channelsCondition": {
              "values": [],
              "isEnabled": false
            },
            "languages": [
              "es",
              "en"
            ],
            "promotionDisplayId": null
          }
        },
        {
          "activityId": "446fc9ec-73f1-43d5-a3ab-89034c9bd6c5",
          "activityName": "notification_center",
          "activityDisplayName": "Offer expired pop-up",
          "events": [
            {
              "eventName": "NotificationSent",
              "eventType": "Completion",
              "nextActivityId": "60b58c3b-7ab6-44d2-8668-ebd970739319"
            },
            {
              "eventName": "NotificationNotSent",
              "eventType": "Completion",
              "nextActivityId": null
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "contract": 5,
            "templates": {
              "es": "tmpl-offer-expired"
            }
          }
        },
        {
          "activityId": "37433fff-7660-4132-89b2-3ae2b0b4491c",
          "activityName": "deposit",
          "activityDisplayName": "Qualifying deposit $100+",
          "events": [
            {
              "eventName": "DepositConditionSatisfied",
              "eventType": "Completion",
              "nextActivityId": "4811cfe1-50d2-4def-8793-7748c55e85ea"
            },
            {
              "eventName": "DepositConditionUnsatisfied",
              "eventType": "Completion",
              "nextActivityId": "094564f6-c21a-4c35-8f66-f488135e6c72"
            },
            {
              "eventName": "DepositConditionCanceled",
              "eventType": "Completion",
              "nextActivityId": null
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "depositConditions": {
              "expirationTimeout": "P0Y0M1DT0H0M0S",
              "minDepositAmounts": [
                {
                  "brand": "JBCL",
                  "amount": 10000,
                  "currencyCode": "CLP"
                }
              ],
              "depositAccountingType": "Any",
              "payGroups": [
                {
                  "names": [],
                  "currencyCode": "CLP"
                }
              ],
              "channelsCondition": {
                "values": [],
                "isEnabled": false
              }
            }
          }
        },
        {
          "activityId": "094564f6-c21a-4c35-8f66-f488135e6c72",
          "activityName": "dextra_sms",
          "activityDisplayName": "Deposit reminder SMS",
          "events": [
            {
              "eventName": "SuccessSmsSend",
              "eventType": "Completion",
              "nextActivityId": "503b8a71-ca2d-4f28-a8dc-3fb8edddf17a"
            },
            {
              "eventName": "FailedSmsSend",
              "eventType": "Completion",
              "nextActivityId": null
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "rawValues": {
              "messageText": "Tu bono te espera — deposita hoy y gira."
            },
            "smsSettings": {}
          }
        },
        {
          "activityId": "4811cfe1-50d2-4def-8793-7748c55e85ea",
          "activityName": "ams_decision_split",
          "activityDisplayName": "Player value split",
          "events": [
            {
              "eventName": "DecisionSplitPassedPath01",
              "eventType": "Completion",
              "nextActivityId": "5227d918-67c2-4312-811e-e8a56f6c7b1b"
            },
            {
              "eventName": "DecisionSplitPassedPath02",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath03",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath04",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath05",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath06",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath07",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath08",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath09",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath10",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath11",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath12",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath13",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath14",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath15",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath16",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath17",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath18",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath19",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedPath20",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "DecisionSplitPassedRemainderPath",
              "eventType": "Completion",
              "nextActivityId": "a3711872-9c2d-42eb-b872-eba8dd40e9c4"
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "rules": [
              {
                "name": "high value",
                "filter": {
                  "property": {
                    "name": "playerValue",
                    "type": "number",
                    "value": "100",
                    "operator": "gte"
                  },
                  "variables": []
                }
              }
            ],
            "remainder": {
              "name": "standard"
            },
            "pathesConfig": [
              {
                "events": [
                  {
                    "eventName": "DecisionSplitPassedPath01",
                    "eventType": "Completion",
                    "eventDisplayName": "high value"
                  }
                ],
                "pathId": "path1",
                "pathName": "high value"
              }
            ]
          }
        },
        {
          "activityId": "5227d918-67c2-4312-811e-e8a56f6c7b1b",
          "activityName": "freespin_bonus",
          "activityDisplayName": "Premium — 100 freespins",
          "events": [
            {
              "eventName": "FreespinBonusCollectingFinished",
              "eventType": "Completion",
              "nextActivityId": "9eafd218-0a5c-4922-a6f0-eb6a66c015e2"
            },
            {
              "eventName": "FreespinBonusNotUsed",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreespinBonusAwardAborted",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreespinBonusRejectConfirmed",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreespinBonusCancelConfirmed",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreeSpinsBonusTermsNotComplied",
              "eventType": "Completion",
              "nextActivityId": null
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "freespinActivity": {
              "spins": 100,
              "provider": "jugabet-games",
              "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
              "spinsExpirationDuration": 86400000
            },
            "allowReject": false
          }
        },
        {
          "activityId": "a3711872-9c2d-42eb-b872-eba8dd40e9c4",
          "activityName": "freespin_bonus",
          "activityDisplayName": "Standard — 30 freespins",
          "events": [
            {
              "eventName": "FreespinBonusCollectingFinished",
              "eventType": "Completion",
              "nextActivityId": "9eafd218-0a5c-4922-a6f0-eb6a66c015e2"
            },
            {
              "eventName": "FreespinBonusNotUsed",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreespinBonusAwardAborted",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreespinBonusRejectConfirmed",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreespinBonusCancelConfirmed",
              "eventType": "Completion",
              "nextActivityId": null
            },
            {
              "eventName": "FreeSpinsBonusTermsNotComplied",
              "eventType": "Completion",
              "nextActivityId": null
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "freespinActivity": {
              "spins": 30,
              "provider": "jugabet-games",
              "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
              "spinsExpirationDuration": 86400000
            },
            "allowReject": false
          }
        },
        {
          "activityId": "9eafd218-0a5c-4922-a6f0-eb6a66c015e2",
          "activityName": "notification_center",
          "activityDisplayName": "You won! (bell)",
          "events": [
            {
              "eventName": "NotificationSent",
              "eventType": "Completion",
              "nextActivityId": "0a7788d2-d70e-4565-a642-5bd6e2311b0e"
            },
            {
              "eventName": "NotificationNotSent",
              "eventType": "Completion",
              "nextActivityId": null
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "contract": 1,
            "templates": {
              "es": "tmpl-reward-granted"
            }
          }
        },
        {
          "activityId": "0a7788d2-d70e-4565-a642-5bd6e2311b0e",
          "activityName": "wait_interval",
          "activityDisplayName": "Wait 1 day",
          "events": [
            {
              "eventName": "WaitTimeCompleted",
              "eventType": "Completion",
              "nextActivityId": "afdf4888-689a-4eb5-a2a9-275862b26274"
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "waitPeriod": "P0Y0M1DT0H0M0S"
          }
        },
        {
          "activityId": "afdf4888-689a-4eb5-a2a9-275862b26274",
          "activityName": "dextra_email",
          "activityDisplayName": "Follow-up email",
          "events": [
            {
              "eventName": "SuccessEmailSend",
              "eventType": "Completion",
              "nextActivityId": "fb1d4028-0d2d-4491-9882-66b5a4f0e6b0"
            },
            {
              "eventName": "FailedEmailSend",
              "eventType": "Completion",
              "nextActivityId": null
            }
          ],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {
            "emailSettings": {
              "contentId": "CSE-0-10001"
            }
          }
        },
        {
          "activityId": "fb1d4028-0d2d-4491-9882-66b5a4f0e6b0",
          "activityName": "end_of_journey",
          "activityDisplayName": "End of journey",
          "events": [],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {}
        },
        {
          "activityId": "60b58c3b-7ab6-44d2-8668-ebd970739319",
          "activityName": "end_of_path",
          "activityDisplayName": "End of path",
          "events": [],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {}
        },
        {
          "activityId": "503b8a71-ca2d-4f28-a8dc-3fb8edddf17a",
          "activityName": "end_of_path",
          "activityDisplayName": "End of path",
          "events": [],
          "dependencies": [],
          "dataDependencies": [],
          "initializationData": {}
        }
      ],
      "rawJourneyData": {
        "elements": [],
        "activitiesConfiguration": {
          "2d499732-04e3-4f8d-b394-2ad77b336a08": {
            "displayName": "API entry"
          },
          "25ba9554-20a9-46e5-9fc6-44f11dd9d84a": {
            "displayName": "Promotion offer"
          },
          "446fc9ec-73f1-43d5-a3ab-89034c9bd6c5": {
            "displayName": "Offer expired pop-up"
          },
          "37433fff-7660-4132-89b2-3ae2b0b4491c": {
            "displayName": "Qualifying deposit $100+"
          },
          "094564f6-c21a-4c35-8f66-f488135e6c72": {
            "displayName": "Deposit reminder SMS"
          },
          "4811cfe1-50d2-4def-8793-7748c55e85ea": {
            "displayName": "Player value split"
          },
          "5227d918-67c2-4312-811e-e8a56f6c7b1b": {
            "displayName": "Premium — 100 freespins"
          },
          "a3711872-9c2d-42eb-b872-eba8dd40e9c4": {
            "displayName": "Standard — 30 freespins"
          },
          "9eafd218-0a5c-4922-a6f0-eb6a66c015e2": {
            "displayName": "You won! (bell)"
          },
          "0a7788d2-d70e-4565-a642-5bd6e2311b0e": {
            "displayName": "Wait 1 day"
          },
          "afdf4888-689a-4eb5-a2a9-275862b26274": {
            "displayName": "Follow-up email"
          },
          "fb1d4028-0d2d-4491-9882-66b5a4f0e6b0": {
            "displayName": "End of journey"
          },
          "60b58c3b-7ab6-44d2-8668-ebd970739319": {
            "displayName": "End of path"
          },
          "503b8a71-ca2d-4f28-a8dc-3fb8edddf17a": {
            "displayName": "End of path"
          }
        },
        "infoValues": {
          "journeyName": "JBCL | PROMO | promotion campaign"
        }
      }
    }
  ];

  const headers = (contentType) => {
    const h = {};
    if (contentType) h['content-type'] = contentType;
    if (MANUAL_TOKEN.trim()) {
      h['authorization'] = 'Bearer ' + MANUAL_TOKEN.trim().replace(/^Bearer\s+/i, '');
    }
    return h;
  };

  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', {
      method: 'POST',
      headers: headers('application/json'),
      body: '{}',
      credentials: 'include',
    });
    const raw = (await r.text()).trim();
    // Response may be a bare string ("JRN-...") or {"journeyId": "JRN-..."}.
    let id = raw.replace(/^"+|"+$/g, '');
    try {
      const data = JSON.parse(raw);
      if (typeof data === 'string') id = data.trim();
      else if (data && typeof data === 'object') {
        id = String(data.identifier || data.journeyId || data.id || data.value || '').trim();
      }
    } catch (e) { /* keep the raw text */ }
    if (!r.ok || !id.startsWith('JRN-')) {
      throw new Error('Failed to reserve journey ID: HTTP ' + r.status + ' ' + raw);
    }
    return id;
  }

  async function createDraft(payload) {
    const r = await fetch(BASE + '/journey-drafts', {
      method: 'POST',
      headers: headers('application/json'),
      body: JSON.stringify(payload),
      credentials: 'include',
    });
    const data = await r.json().catch(() => null);
    if (!r.ok) {
      throw new Error('Create failed: HTTP ' + r.status + ' ' + JSON.stringify(data));
    }
    return data;
  }

  async function publishJourney(journeyId) {
    const r = await fetch(BASE + '/journeys/' + journeyId + '/publish', {
      method: 'POST',
      headers: headers('application/json'),
      credentials: 'include',
    });
    if (!r.ok) {
      const raw = await r.text();
      throw new Error('Publish failed: HTTP ' + r.status + ' ' + raw);
    }
    return r.json();
  }

  const created = [];
  for (const payload of PAYLOADS) {
    const journeyId = await reserveId();
    payload.journeyId = journeyId;
    payload.reservedJourneyId = journeyId;
    console.log('Reserved', journeyId, '->', payload.journeyName);
    const draft = await createDraft(payload);
    let status = draft.status;
    if (PUBLISH) {
      const published = await publishJourney(journeyId);
      status = published.status;
      if (published.webhooks && published.webhooks.length) {
        console.log('  webhooks:', published.webhooks.map((w) => w.webhookId).join(', '));
      }
    }
    created.push(journeyId + ' (' + status + ')');
    console.log('%cCreated ' + journeyId + ' — ' + status, 'color:#22c55e;font-weight:bold');
  }
  console.log('%cDONE: ' + created.join(', '), 'color:#22c55e;font-weight:bold;font-size:14px');
})();
