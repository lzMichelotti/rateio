# One VPC, three subnets. The EC2 instance lives in the public subnet; the RDS
# instance in the private ones, which have no route out of the VPC. No NAT
# Gateway, no interface endpoints.
#
# Zones are named, not looked up: a data source could reorder them and force the
# subnets to be replaced. Both t4g.micro and db.t4g.micro are offered in 1a and
# 1b (us-east-1e offers neither). The instance and the database share 1a, so
# their traffic never crosses zones, which is billed.

locals {
  zone_primary   = "us-east-1a"
  zone_secondary = "us-east-1b"
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"

  tags = {
    Name = "rateio"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "rateio"
  }
}

# Public: what makes it public is the route to the internet gateway below, not
# this resource. The automatic public IP is what lets the instance open
# connections out through that gateway.
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.0.0/24"
  availability_zone       = local.zone_primary
  map_public_ip_on_launch = true

  tags = {
    Name = "rateio-public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "rateio-public"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Private: no association, so they use the VPC's main route table, which holds
# only the local route (10.0.0.0/16). Nothing here can reach the internet, and
# the internet cannot reach anything here. The RDS subnet group requires two
# zones even for a single-AZ instance.
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.10.0/24"
  availability_zone = local.zone_primary

  tags = {
    Name = "rateio-private-a"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.11.0/24"
  availability_zone = local.zone_secondary

  tags = {
    Name = "rateio-private-b"
  }
}
