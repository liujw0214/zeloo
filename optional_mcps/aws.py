"""AWS MCP — EC2, S3, Lambda management via boto3."""

from __future__ import annotations

import json
import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_boto_client(service: str) -> Any:
    try:
        import boto3
        return boto3.client(service, region_name=AWS_REGION)
    except ImportError:
        return None


@make_tool
def aws_list_ec2_instances(
    state: str = "running",
) -> str:
    """List EC2 instances in the current region.

    Args:
        state: Filter by instance state (running, stopped, etc.).
    """
    client = _get_boto_client("ec2")
    if client is None:
        return json.dumps({"error": "boto3 not installed"})
    try:
        filters = [{"Name": "instance-state-name", "Values": [state]}] if state else []
        resp = client.describe_instances(Filters=filters)
        instances = []
        for reservation in resp.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                instances.append({
                    "InstanceId": inst.get("InstanceId"),
                    "InstanceType": inst.get("InstanceType"),
                    "State": inst.get("State", {}).get("Name"),
                    "PublicIpAddress": inst.get("PublicIpAddress"),
                    "PrivateIpAddress": inst.get("PrivateIpAddress"),
                    "Tags": inst.get("Tags", []),
                })
        return json.dumps({"instances": instances, "count": len(instances)}, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def aws_list_s3_buckets() -> str:
    """List all S3 buckets in the account."""
    client = _get_boto_client("s3")
    if client is None:
        return json.dumps({"error": "boto3 not installed"})
    try:
        resp = client.list_buckets()
        buckets = [
            {
                "Name": b.get("Name"),
                "CreationDate": str(b.get("CreationDate", "")),
            }
            for b in resp.get("Buckets", [])
        ]
        return json.dumps({"buckets": buckets, "count": len(buckets)}, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def aws_list_lambda_functions(
    limit: int = 50,
) -> str:
    """List Lambda functions in the current region.

    Args:
        limit: Maximum number of functions to return.
    """
    client = _get_boto_client("lambda")
    if client is None:
        return json.dumps({"error": "boto3 not installed"})
    try:
        resp = client.list_functions(MaxItems=limit)
        functions = [
            {
                "FunctionName": f.get("FunctionName"),
                "Runtime": f.get("Runtime"),
                "Handler": f.get("Handler"),
                "MemorySize": f.get("MemorySize"),
                "Timeout": f.get("Timeout"),
            }
            for f in resp.get("Functions", [])
        ]
        return json.dumps({"functions": functions, "count": len(functions)}, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def aws_get_account_info() -> str:
    """Get AWS account information (ID, alias, etc.)."""
    client = _get_boto_client("iam")
    if client is None:
        return json.dumps({"error": "boto3 not installed"})
    try:
        client.get_account_summary()
        sts = _get_boto_client("sts")
        identity = sts.get_caller_identity()
        return json.dumps({
            "AccountId": identity.get("Account"),
            "Arn": identity.get("Arn"),
            "UserId": identity.get("UserId"),
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@make_tool
def aws_list_iam_users(limit: int = 50) -> str:
    """List IAM users in the account.

    Args:
        limit: Maximum number of users to return.
    """
    client = _get_boto_client("iam")
    if client is None:
        return json.dumps({"error": "boto3 not installed"})
    try:
        resp = client.list_users(MaxItems=limit)
        users = [
            {
                "UserName": u.get("UserName"),
                "UserId": u.get("UserId"),
                "Arn": u.get("Arn"),
                "CreateDate": str(u.get("CreateDate", "")),
            }
            for u in resp.get("Users", [])
        ]
        return json.dumps({"users": users, "count": len(users)}, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


TOOLS = [
    aws_list_ec2_instances,
    aws_list_s3_buckets,
    aws_list_lambda_functions,
    aws_get_account_info,
    aws_list_iam_users,
]


class AWSMCPServer(MCPServer):
    name = "aws"
    description = "AWS EC2, S3, Lambda, IAM management via boto3"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["AWSMCPServer", "TOOLS"]
