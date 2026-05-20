// Standard C libraries
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <net/if.h>
#include <arpa/inet.h>
#include <sys/socket.h>

// Netlink (rtnetlink)
#include <linux/netlink.h>
#include <linux/rtnetlink.h>

#define PORT 9106
#define MAX_IFACES 16

struct eth_data {
    char ifname[32];
    unsigned long long rx_bytes;
    unsigned long long tx_bytes;
    unsigned long long rx_packets;
    unsigned long long tx_packets;
    unsigned long long rx_errors;
    unsigned long long tx_errors;
    unsigned int mtu;
    unsigned int operstate;
};

static struct eth_data dataResult[MAX_IFACES];
static int result_count = 0;

static int nl_send_req(int sock, int type, int flags) {
    struct {
        struct nlmsghdr nh;
        struct ifinfomsg ifi;
    } req;

    memset(&req, 0, sizeof(req));

    req.nh.nlmsg_len = NLMSG_LENGTH(sizeof(struct ifinfomsg));
    req.nh.nlmsg_type = type;
    req.nh.nlmsg_flags = NLM_F_REQUEST | flags;
    req.ifi.ifi_family = AF_PACKET;

    return send(sock, &req, req.nh.nlmsg_len, 0);
}


static void parse_link(struct nlmsghdr *nh) {
    struct ifinfomsg *ifi = NLMSG_DATA(nh);
    struct rtattr *attr = IFLA_RTA(ifi);
    int len = IFLA_PAYLOAD(nh);

    if (result_count >= MAX_IFACES)
        return;

    struct eth_data *d = &dataResult[result_count];

    memset(d, 0, sizeof(*d));

    d->operstate = ifi->ifi_flags;

    for (; RTA_OK(attr, len); attr = RTA_NEXT(attr, len)) {

        switch (attr->rta_type) {

        case IFLA_IFNAME:
            strncpy(d->ifname, RTA_DATA(attr), sizeof(d->ifname)-1);
            break;

        case IFLA_MTU:
            d->mtu = *(unsigned int *)RTA_DATA(attr);
            break;

        case IFLA_STATS:
        {
            struct rtnl_link_stats *st = RTA_DATA(attr);
            d->rx_bytes = st->rx_bytes;
            d->tx_bytes = st->tx_bytes;
            d->rx_packets = st->rx_packets;
            d->tx_packets = st->tx_packets;
            d->rx_errors = st->rx_errors;
            d->tx_errors = st->tx_errors;
            break;
        }

        default:
            break;
        }
    }

    result_count++;
}


void perform_eth_scan() {
    result_count = 0;

    int sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);

    struct sockaddr_nl sa = {
        .nl_family = AF_NETLINK
    };

    bind(sock, (struct sockaddr*)&sa, sizeof(sa));

    nl_send_req(sock, RTM_GETLINK, NLM_F_DUMP);

    char buffer[8192];

    int len = recv(sock, buffer, sizeof(buffer), 0);

    struct nlmsghdr *nh = (struct nlmsghdr *)buffer;

    for (; NLMSG_OK(nh, len); nh = NLMSG_NEXT(nh, len)) {

        if (nh->nlmsg_type == NLMSG_DONE)
            break;

        if (nh->nlmsg_type == RTM_NEWLINK)
            parse_link(nh);
    }

    close(sock);
}


void metrics(int client_fd) {

    dprintf(client_fd,
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/plain; version=0.0.4\r\n"
        "Connection: close\r\n"
        "\r\n");

    dprintf(client_fd,
        "# HELP eth_rx_bytes Ethernet RX bytes\n"
        "# TYPE eth_rx_bytes counter\n");

    for (int i = 0; i < result_count; i++) {

        dprintf(client_fd,
            "eth_rx_bytes{iface=\"%s\"} %llu\n",
            dataResult[i].ifname,
            dataResult[i].rx_bytes);

        dprintf(client_fd,
            "eth_tx_bytes{iface=\"%s\"} %llu\n",
            dataResult[i].ifname,
            dataResult[i].tx_bytes);

        dprintf(client_fd,
            "eth_rx_errors{iface=\"%s\"} %llu\n",
            dataResult[i].ifname,
            dataResult[i].rx_errors);

        dprintf(client_fd,
            "eth_tx_errors{iface=\"%s\"} %llu\n",
            dataResult[i].ifname,
            dataResult[i].tx_errors);

        dprintf(client_fd,
            "eth_mtu{iface=\"%s\"} %u\n",
            dataResult[i].ifname,
            dataResult[i].mtu);
    }

    fsync(client_fd);
}


void start_metrics() {

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(PORT),
        .sin_addr.s_addr = INADDR_ANY
    };

    bind(server_fd, (struct sockaddr*)&addr, sizeof(addr));
    listen(server_fd, 5);

    while (1) {

        int client = accept(server_fd, NULL, NULL);

        perform_eth_scan();

        metrics(client);

        shutdown(client, SHUT_WR);
        close(client);
    }
}


int main() {
    start_metrics();
    return 0;
}