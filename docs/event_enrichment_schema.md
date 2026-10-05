## LLM Event Enrichment Schema

The LLM is used to enrich raw event records with structured information that may not be available directly from the original event source.

The output should be as structured and objective as possible. Free-text descriptions should be avoided. If a value cannot be determined reliably, it should be returned as `null` or `unknown` rather than guessed.

### Variables

| Variable              | Type              | Description                                                                                                                                                                    |
| --------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `event_type`          | `string`          | Broad category of the event, such as `concert`, `music_festival`, `sports`, `conference`, `exhibition`, `cultural`, or `other`.                                                |
| `event_subtype`       | `string`          | More specific event format. For music events, examples include `club_concert`, `theatre_concert`, `arena_concert`, `stadium_concert`, `outdoor_concert`, and `music_festival`. |
| `doors_time`          | `string \| null`  | Time when doors or gates open, represented as `HH:MM`.                                                                                                                         |
| `start_time`          | `string \| null`  | Scheduled start time of the event, represented as `HH:MM`.                                                                                                                     |
| `end_time`            | `string \| null`  | Scheduled or expected end time of the event, represented as `HH:MM`.                                                                                                           |
| `venue_capacity`      | `integer \| null` | Approximate capacity of the venue for the relevant event configuration.                                                                                                        |
| `expected_attendance` | `integer \| null` | Number of attendees expected before the event. This is intended to represent information that could potentially be known at forecasting time.                                  |
| `actual_attendance`   | `integer \| null` | Reported number of attendees after the event. This should be kept separate from expected attendance because it may not be available at forecasting time.                       |
| `sold_out`            | `boolean \| null` | Indicates whether the event was reported as sold out. `null` should be used when this information is unknown.                                                                  |
| `indoor_outdoor`      | `string`          | Physical setting of the event. Allowed values: `indoor`, `outdoor`, `mixed`, `unknown`.                                                                                        |
| `audience_draw`       | `string`          | Approximate geographical reach of the event. Allowed values: `local`, `regional`, `national`, `international`, `unknown`.                                                      |
| `source_urls`         | `list[string]`    | URLs of sources used to extract or verify the event information.                                                                                                               |
| `confidence`          | `object`          | Confidence scores for extracted variables, typically represented as values between `0.0` and `1.0`.                                                                            |

### Allowed categorical values

#### `event_type`

```text
concert
music_festival
sports
conference
exhibition
cultural
other
```

#### `event_subtype`

For music events:

```text
club_concert
theatre_concert
arena_concert
stadium_concert
outdoor_concert
music_festival
other
```

#### `indoor_outdoor`

```text
indoor
outdoor
mixed
unknown
```

#### `audience_draw`

```text
local
regional
national
international
unknown
```

### Example output

```json
{
  "event_type": "concert",
  "event_subtype": "stadium_concert",
  "doors_time": "17:00",
  "start_time": "20:00",
  "end_time": "22:30",
  "venue_capacity": 38000,
  "expected_attendance": 35000,
  "actual_attendance": null,
  "sold_out": true,
  "indoor_outdoor": "outdoor",
  "audience_draw": "international",
  "source_urls": [
    "https://example.com/event"
  ],
  "confidence": {
    "doors_time": 0.80,
    "start_time": 0.95,
    "end_time": 0.70,
    "venue_capacity": 0.95,
    "expected_attendance": 0.75,
    "actual_attendance": 0.0,
    "sold_out": 0.90,
    "indoor_outdoor": 0.95,
    "audience_draw": 0.85
  }
}
```

The LLM should prefer missing values over unsupported assumptions. In particular, unknown attendance, timing, or sold-out status should not be inferred without evidence.
