
# Database Load Test

## 1. Test configuration

| Metric | Value |
|---|---:|
| Links seeded | 5,000 |
| Click events seeded | 50,000 |
| Benchmark repetitions | 10 |
| Database engine | Moto (in-memory DynamoDB mock) |
| Seed duration | 37.57 seconds |

## 2. Latency results

Unit: milliseconds (ms).

| Operation | Min | Average | Max |
|---|---:|---:|---:|
| get_link | 4.522 | 5.423 | 6.869 |
| list_owner_links (5,000 links) | 4930.992 | 5217.711 | 6157.059 |
| get_stats (50,000 clicks aggregated) | 120.051 | 135.328 | 157.110 |
| purge_link_data (50,000 clicks) | 46332.996 | N/A | N/A |

## 3. Verification

- [x] 5,000 links inserted.
- [x] 50,000 click events inserted.
- [x] get_stats returned 50,000 clicks.
- [x] purge_link_data removed all target click events.
- [x] purge_link_data removed all target link statistics.

Remaining target click events: 0

Remaining target link-stat items: 0

## 4. Known Limitations (Giới hạn đã biết)

| Component | Configuration | Potential limitation |
|---|---|---|
| Clicks table | 4 WCU | Limited write throughput; high write rates may cause throttling. |
| Delete-link Lambda | 15-second timeout | Deleting a large number of click records may exceed the execution timeout. |

### Estimated impact

- The Clicks table has only 4 WCU. Assuming standard items up to 1 KB, it supports approximately 4 writes per second under ideal conditions.
- Deleting a link with more than approximately 1,200 click records may encounter throttling or Lambda timeout, depending on request rate, pagination, retries, and execution time.
- At 4 writes per second, processing 1,200 individual writes would theoretically take approximately 300 seconds without batching or parallel processing.

### Important note

These values are estimates, not measured AWS limits or actual failure results.

The local benchmark uses Moto, which does not simulate DynamoDB provisioned-throughput throttling or actual AWS Lambda execution time. Therefore, these limitations must be verified in an AWS environment before drawing conclusions about real production behavior.

## 5. Benchmark Limitations

This benchmark uses Moto, an in-memory AWS service mock.

The latency measurements are useful for comparing application logic in this local test environment. They do not represent actual DynamoDB network latency, provisioned capacity, throttling, or AWS Lambda execution time.

The purge operation is measured once because it deletes the target test data.
