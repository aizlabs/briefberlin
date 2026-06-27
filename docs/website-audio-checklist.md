# Website Audio AWS Runbook

This runbook provisions private S3 storage and CloudFront delivery for website audio at
`https://media.briefberlin.de/articles/.../article.mp3`.

Audio scripts and generated audio must come only from the public learner article. Never use
private source text, base article drafts, logs, metrics, prompts, or intermediate private files
as audio input or uploaded audio metadata.

## 1. AWS CLI And Profile Preflight

Run from the repository root:

```bash
aws --version
aws configure list-profiles
aws configure get region
aws sts get-caller-identity
```

Confirm the AWS account, CLI profile, and region before making changes. The S3 bucket is in
`eu-central-1`; ACM for CloudFront must be requested in `us-east-1`.

If using a named profile, export it before continuing:

```bash
export AWS_PROFILE=your-profile
```

Set the reusable names:

```bash
export AUDIO_BUCKET=briefberlin-audio-prod
export AUDIO_BUCKET_REGION=eu-central-1
export AUDIO_DOMAIN=media.briefberlin.de
export AUDIO_PREFIX=articles
export CF_CERT_REGION=us-east-1
```

## 2. S3 Bucket

Create or reuse the private bucket:

```bash
aws s3api head-bucket --bucket "$AUDIO_BUCKET" || \
aws s3api create-bucket \
  --bucket "$AUDIO_BUCKET" \
  --region "$AUDIO_BUCKET_REGION" \
  --create-bucket-configuration LocationConstraint="$AUDIO_BUCKET_REGION"
```

Block public access:

```bash
aws s3api put-public-access-block \
  --bucket "$AUDIO_BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

Enforce bucket-owner ownership:

```bash
aws s3api put-bucket-ownership-controls \
  --bucket "$AUDIO_BUCKET" \
  --ownership-controls '{
    "Rules": [
      {
        "ObjectOwnership": "BucketOwnerEnforced"
      }
    ]
  }'
```

Enable default encryption:

```bash
aws s3api put-bucket-encryption \
  --bucket "$AUDIO_BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [
      {
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        },
        "BucketKeyEnabled": true
      }
    ]
  }'
```

## 3. ACM Certificate In us-east-1

Find an existing certificate:

```bash
aws acm list-certificates \
  --region "$CF_CERT_REGION" \
  --certificate-statuses ISSUED PENDING_VALIDATION \
  --query "CertificateSummaryList[?DomainName=='$AUDIO_DOMAIN']"
```

Request one if needed:

```bash
export AUDIO_CERT_ARN="$(aws acm request-certificate \
  --region "$CF_CERT_REGION" \
  --domain-name "$AUDIO_DOMAIN" \
  --validation-method DNS \
  --query CertificateArn \
  --output text)"
```

Print the external DNS validation CNAME:

```bash
aws acm describe-certificate \
  --region "$CF_CERT_REGION" \
  --certificate-arn "$AUDIO_CERT_ARN" \
  --query "Certificate.DomainValidationOptions[].ResourceRecord" \
  --output table
```

Add the printed CNAME at the external DNS provider for `briefberlin.de`, then wait until ACM is
issued:

```bash
aws acm wait certificate-validated \
  --region "$CF_CERT_REGION" \
  --certificate-arn "$AUDIO_CERT_ARN"
```

## 4. CloudFront OAC

Create an Origin Access Control if one does not already exist:

```bash
aws cloudfront list-origin-access-controls \
  --query "OriginAccessControlList.Items[?Name=='briefberlin-audio-oac']"
```

```bash
cat > /tmp/briefberlin-audio-oac.json <<'JSON'
{
  "Name": "briefberlin-audio-oac",
  "Description": "BriefBerlin private audio S3 origin access",
  "SigningProtocol": "sigv4",
  "SigningBehavior": "always",
  "OriginAccessControlOriginType": "s3"
}
JSON

export AUDIO_OAC_ID="$(aws cloudfront create-origin-access-control \
  --origin-access-control-config file:///tmp/briefberlin-audio-oac.json \
  --query "OriginAccessControl.Id" \
  --output text)"
```

## 5. CloudFront Distribution

Create or reuse a distribution with:

- Alias: `media.briefberlin.de`
- Origin: `briefberlin-audio-prod.s3.eu-central-1.amazonaws.com`
- Viewer protocol policy: redirect HTTP to HTTPS
- Certificate: ACM certificate for `media.briefberlin.de` in `us-east-1`
- OAC: `briefberlin-audio-oac`

Create config in `/tmp`:

```bash
export AUDIO_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export AUDIO_ORIGIN_ID="briefberlin-audio-prod-s3"

cat > /tmp/briefberlin-audio-distribution.json <<JSON
{
  "CallerReference": "briefberlin-audio-$(date +%Y%m%d%H%M%S)",
  "Comment": "BriefBerlin private website audio",
  "Enabled": true,
  "Aliases": {
    "Quantity": 1,
    "Items": [
      "$AUDIO_DOMAIN"
    ]
  },
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "$AUDIO_ORIGIN_ID",
        "DomainName": "$AUDIO_BUCKET.s3.$AUDIO_BUCKET_REGION.amazonaws.com",
        "OriginAccessControlId": "$AUDIO_OAC_ID",
        "S3OriginConfig": {
          "OriginAccessIdentity": ""
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "$AUDIO_ORIGIN_ID",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": [
        "GET",
        "HEAD"
      ],
      "CachedMethods": {
        "Quantity": 2,
        "Items": [
          "GET",
          "HEAD"
        ]
      }
    },
    "Compress": false,
    "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
    "TrustedSigners": {
      "Enabled": false,
      "Quantity": 0
    },
    "TrustedKeyGroups": {
      "Enabled": false,
      "Quantity": 0
    }
  },
  "ViewerCertificate": {
    "ACMCertificateArn": "$AUDIO_CERT_ARN",
    "SSLSupportMethod": "sni-only",
    "MinimumProtocolVersion": "TLSv1.2_2021",
    "Certificate": "$AUDIO_CERT_ARN",
    "CertificateSource": "acm"
  },
  "DefaultRootObject": "",
  "PriceClass": "PriceClass_100",
  "HttpVersion": "http2",
  "IsIPV6Enabled": true
}
JSON

aws cloudfront create-distribution \
  --distribution-config file:///tmp/briefberlin-audio-distribution.json
```

Record the returned distribution ID, ARN, and domain name, for example
`d123abc.cloudfront.net`.

## 6. Restrictive S3 Bucket Policy

Allow reads only from the CloudFront distribution ARN:

```bash
export AUDIO_DISTRIBUTION_ID=E123EXAMPLE
export AUDIO_DISTRIBUTION_ARN="arn:aws:cloudfront::$AUDIO_ACCOUNT_ID:distribution/$AUDIO_DISTRIBUTION_ID"

cat > /tmp/briefberlin-audio-bucket-policy.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowCloudFrontServicePrincipalReadOnly",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudfront.amazonaws.com"
      },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$AUDIO_BUCKET/$AUDIO_PREFIX/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "$AUDIO_DISTRIBUTION_ARN"
        }
      }
    }
  ]
}
JSON

aws s3api put-bucket-policy \
  --bucket "$AUDIO_BUCKET" \
  --policy file:///tmp/briefberlin-audio-bucket-policy.json
```

## 7. External DNS Handoff

After the CloudFront distribution is deployed, add this CNAME at the external DNS provider:

```text
Name:  media.briefberlin.de
Type:  CNAME
Value: <cloudfront-distribution-domain-name>
```

Do not create this final CNAME until CloudFront has the `media.briefberlin.de` alias and the ACM
certificate is issued.

## 8. Local Environment

Use these local `.env` values when audio delivery is ready:

```bash
AUDIO_ENABLED=true
AUDIO_UPLOAD_ENABLED=true
AUDIO_PROVIDER=openai
AUDIO_VOICE=alloy
AUDIO_FORMAT=mp3
AUDIO_PUBLIC_BASE_URL=https://media.briefberlin.de
AUDIO_S3_BUCKET=briefberlin-audio-prod
AUDIO_S3_REGION=eu-central-1
AUDIO_S3_PREFIX=articles
```

Keep `AUDIO_OUTPUT_PATH=./output/audio` for local working files. `output/audio` must remain
uncommitted.

## 9. Verification

Verify bucket settings:

```bash
aws s3api get-public-access-block --bucket "$AUDIO_BUCKET"
aws s3api get-bucket-ownership-controls --bucket "$AUDIO_BUCKET"
aws s3api get-bucket-encryption --bucket "$AUDIO_BUCKET"
aws s3 ls "s3://$AUDIO_BUCKET/$AUDIO_PREFIX/"
```

Verify CloudFront:

```bash
aws cloudfront get-distribution --id "$AUDIO_DISTRIBUTION_ID" \
  --query "Distribution.{Status:Status,DomainName:DomainName,Aliases:DistributionConfig.Aliases.Items}"
```

After uploading an article audio file and adding DNS, verify delivery:

```bash
curl -I "https://media.briefberlin.de/articles/YYYY/MM/article-slug/article.mp3"
```

Expected: HTTPS response from CloudFront with an audio content type such as `audio/mpeg`.
