AWS RDS (PostgreSQL) Setup
==========================

Recommended Minimal Production Setup
------------------------------------
- Instance class: `db.t4g.micro` (ARM) or `db.t3.micro` (x86), Single-AZ
- Storage: `gp3`, 20–40 GB, autoscaling on
- Public access: OFF
- Security: allow inbound `5432` only from your EC2 security group
- Backups: retention 7 days, deletion protection ON
- Monitoring: Enhanced monitoring optional; enable CloudWatch alarms later

Networking
----------
- Place the RDS instance in the same VPC as your EC2.
- Create a DB Subnet Group with at least 2 private subnets across AZs.
- Security Group rules:
  - Inbound: TCP 5432 from your EC2 Security Group ID only
  - Outbound: default

Parameter Group (optional)
--------------------------
- Create a custom parameter group if you need:
  - `rds.force_ssl = 1`
  - Enable extensions via SQL after DB created

Create Database/User
--------------------
`psql` from EC2 (install client if needed):
`sudo dnf install -y postgresql15` (Amazon Linux 2023) or `sudo apt install -y postgresql-client`

Then:
```
psql "host=<rds-endpoint> port=5432 dbname=postgres user=postgres password=<master-password> sslmode=require" -c "CREATE DATABASE confio;"
psql "host=<rds-endpoint> port=5432 dbname=confio user=postgres password=<master-password> sslmode=require" -c "CREATE USER confio_app WITH PASSWORD '<strong-password>';"
psql "host=<rds-endpoint> port=5432 dbname=confio user=postgres password=<master-password> sslmode=require" -c "GRANT ALL PRIVILEGES ON DATABASE confio TO confio_app;"
```

Enable Extensions (if using PostGIS/pgcrypto/pg_trgm)
-----------------------------------------------------
```
psql "host=<rds-endpoint> port=5432 dbname=confio user=confio_app password=<password> sslmode=require" <<SQL
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
```

Django Configuration
--------------------
- Edit `/opt/confio/.env` on EC2:
```
DB_NAME=confio
DB_USER=confio_app
DB_PASSWORD=<password>
DB_HOST=<rds-endpoint>
DB_PORT=5432
DB_SSLMODE=require
DB_CONN_MAX_AGE=300
```

- Settings support SSL and connection pooling via env:
  - `DB_SSLMODE` (default `prefer`) → set `require` for RDS
  - `DB_CONN_MAX_AGE` (default `300`)

Apply Migrations
----------------
```
sudo /opt/confio/venv/bin/python /opt/confio/manage.py migrate --noinput
sudo /opt/confio/venv/bin/python /opt/confio/manage.py collectstatic --noinput
```

Systemd Restart
---------------
```
sudo systemctl restart daphne
sudo systemctl restart celery
sudo systemctl restart celery-beat
```

Terraform (Optional)
--------------------
```
resource "aws_db_subnet_group" "confio" {
  name       = "confio-db"
  subnet_ids = [var.private_subnet_a, var.private_subnet_b]
}

resource "aws_security_group" "rds" {
  name   = "confio-rds"
  vpc_id = var.vpc_id
  ingress {
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [var.ec2_sg_id]
  }
  egress { protocol = "-1" from_port = 0 to_port = 0 cidr_blocks = ["0.0.0.0/0"] }
}

resource "aws_db_instance" "confio" {
  identifier                 = "confio-db"
  engine                     = "postgres"
  engine_version             = "16.4"
  instance_class             = "db.t4g.micro"
  allocated_storage          = 20
  storage_type               = "gp3"
  db_name                    = "confio"
  username                   = "postgres"
  password                   = var.master_password
  db_subnet_group_name       = aws_db_subnet_group.confio.name
  vpc_security_group_ids     = [aws_security_group.rds.id]
  publicly_accessible        = false
  deletion_protection        = true
  backup_retention_period    = 7
  skip_final_snapshot        = false
  apply_immediately          = true
}
```

Notes
-----
- Prefer Secrets Manager + IAM to store credentials and rotate later.
- Ensure EC2’s security group is referenced in the RDS security group for least-privilege network access.

