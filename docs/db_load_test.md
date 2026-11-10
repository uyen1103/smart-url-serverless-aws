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

## 4. Load threshold estimation

The Clicks table is configured with 4 WCU.

A single standard DynamoDB write of an item up to 1 KB consumes approximately 1 WCU. Under ideal conditions, 4 WCU supports approximately 4 such writes per second.

For 1,200 click writes:

- Ideal minimum write time: approximately 300 seconds at 4 writes/second.
- A burst of 1,200 writes in a short period can exceed provisioned throughput.
- Actual throttling depends on item size, traffic distribution, burst capacity, retries, and concurrent requests.

The delete-link Lambda has a 15-second timeout. Purging 50,000 click records may require multiple Query and BatchWriteItem requests. Whether it times out depends on request latency, pagination, retry behavior, and throughput.

These are theoretical estimates, not measured AWS throttling or Lambda timeout results.

## 5. Limitations

This benchmark uses Moto, an in-memory AWS service mock.

The latency measurements are useful for comparing application logic in this local test environment. They do not represent actual DynamoDB network latency, provisioned capacity, throttling, or AWS Lambda execution time.

The purge operation is measured once because it deletes the target test data.
