import json


def lambda_handler(event, context):
    """Lambda hello-world, chỉ để kiểm tra môi trường SAM + API Gateway chạy được."""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"message": "hello from smart-url"}),
    }
