// gcc wifi_test.c -o wifi_test -I/usr/include/libnl3 -lnl-3 -lnl-genl-3

#include <stdint.h>
#include <stdio.h>
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <unistd.h>
#include <string.h>

#include <netlink/handlers.h>
#include <netlink/netlink.h>
#include <netlink/socket.h>
#include <netlink/genl/genl.h>
#include <netlink/genl/ctrl.h>
#include <netlink/attr.h>
#include <netlink/msg.h>

#include <linux/genetlink.h>
#include <linux/netlink.h>
#include <linux/nl80211.h>

#include <net/if.h>

#define MAX_RESULTS 256

struct wifi_data
{
    int frequency;
    char bssid[20];
    char ssid[33];
    int mbm;
    int msAgo;
};

static struct wifi_data dataResult[MAX_RESULTS];
static int result_count = 0;

struct trigger_results
{
    int done;
    int aborted;
};

static int error_handler(struct sockaddr_nl *nla, struct nlmsgerr *err, void *arg)
{
    int *ret = arg;
    *ret = err->error;
    fprintf(stderr, "netlink error: %d\n", err->error);
    return NL_STOP;
}

static int finish_handler(struct nl_msg *msg, void *arg)
{
    int *ret = arg;
    *ret = 0;
    return NL_SKIP;
}

static int ack_handler(struct nl_msg *msg, void *arg)
{
    int *ret = arg;
    *ret = 0;
    return NL_STOP;
}

static int no_seq_check(struct nl_msg *msg, void *arg)
{
    return NL_OK;
}

static void json_escape(const char *in, char *out, size_t out_size)
{
    size_t pos = 0;

    for (size_t i = 0; in[i] != '\0' && pos + 2 < out_size; i++)
    {
        unsigned char c = (unsigned char)in[i];

        if (c == '"' || c == '\\')
        {
            if (pos + 2 >= out_size)
                break;
            out[pos++] = '\\';
            out[pos++] = c;
        }
        else if (isprint(c))
        {
            out[pos++] = c;
        }
        else
        {
            out[pos++] = '?';
        }
    }

    out[pos] = '\0';
}

void get_bssid(char *mac_addr, unsigned char *arg)
{
    sprintf(mac_addr, "%02x:%02x:%02x:%02x:%02x:%02x",
            arg[0], arg[1], arg[2], arg[3], arg[4], arg[5]);
}

void get_ssid(char *out, unsigned char *ie, int ielen)
{
    while (ielen >= 2 && ielen >= ie[1] + 2)
    {
        if (ie[0] == 0 && ie[1] <= 32)
        {
            int len = ie[1];
            unsigned char *data = ie + 2;
            int pos = 0;

            for (int i = 0; i < len && pos < 32; i++)
            {
                if (isprint(data[i]) && data[i] != '\\' && data[i] != '"')
                    out[pos++] = data[i];
                else
                    out[pos++] = '?';
            }

            out[pos] = '\0';

            if (pos == 0)
                strcpy(out, "hidden");

            return;
        }

        ielen -= ie[1] + 2;
        ie += ie[1] + 2;
    }

    strcpy(out, "hidden");
}

static int callback_trigger(struct nl_msg *msg, void *arg)
{
    struct genlmsghdr *gnlh = nlmsg_data(nlmsg_hdr(msg));
    struct trigger_results *results = arg;

    if (gnlh->cmd == NL80211_CMD_SCAN_ABORTED)
    {
        results->done = 1;
        results->aborted = 1;
    }
    else if (gnlh->cmd == NL80211_CMD_NEW_SCAN_RESULTS)
    {
        results->done = 1;
        results->aborted = 0;
    }

    return NL_SKIP;
}

static int callback_dump(struct nl_msg *msg, void *arg)
{
    struct genlmsghdr *gnlh = nlmsg_data(nlmsg_hdr(msg));
    struct nlattr *tb[NL80211_ATTR_MAX + 1];
    struct nlattr *bss[NL80211_BSS_MAX + 1];

    static struct nla_policy bss_policy[NL80211_BSS_MAX + 1] = {
        [NL80211_BSS_FREQUENCY] = {.type = NLA_U32},
        [NL80211_BSS_BSSID] = {},
        [NL80211_BSS_INFORMATION_ELEMENTS] = {},
        [NL80211_BSS_SIGNAL_MBM] = {.type = NLA_U32},
        [NL80211_BSS_SEEN_MS_AGO] = {.type = NLA_U32},
    };

    nla_parse(tb, NL80211_ATTR_MAX, genlmsg_attrdata(gnlh, 0), genlmsg_attrlen(gnlh, 0), NULL);

    if (!tb[NL80211_ATTR_BSS])
    {
        fprintf(stderr, "bss info missing\n");
        return NL_SKIP;
    }

    if (nla_parse_nested(bss, NL80211_BSS_MAX, tb[NL80211_ATTR_BSS], bss_policy))
    {
        fprintf(stderr, "failed to parse nested attributes\n");
        return NL_SKIP;
    }

    if (!bss[NL80211_BSS_BSSID] || !bss[NL80211_BSS_INFORMATION_ELEMENTS])
    {
        fprintf(stderr, "bssid or information elements missing\n");
        return NL_SKIP;
    }

    if (result_count >= MAX_RESULTS)
        return NL_SKIP;

    dataResult[result_count].frequency = 0;
    dataResult[result_count].mbm = 0;
    dataResult[result_count].msAgo = 0;

    if (bss[NL80211_BSS_FREQUENCY])
        dataResult[result_count].frequency = nla_get_u32(bss[NL80211_BSS_FREQUENCY]);

    get_bssid(dataResult[result_count].bssid, nla_data(bss[NL80211_BSS_BSSID]));

    get_ssid(
        dataResult[result_count].ssid,
        nla_data(bss[NL80211_BSS_INFORMATION_ELEMENTS]),
        nla_len(bss[NL80211_BSS_INFORMATION_ELEMENTS]));

    if (bss[NL80211_BSS_SIGNAL_MBM])
        dataResult[result_count].mbm = (int)nla_get_u32(bss[NL80211_BSS_SIGNAL_MBM]);

    if (bss[NL80211_BSS_SEEN_MS_AGO])
        dataResult[result_count].msAgo = (int)nla_get_u32(bss[NL80211_BSS_SEEN_MS_AGO]);

    result_count++;
    return NL_SKIP;
}

int do_scan_trigger(struct nl_sock *socket, int if_index, int driver_id)
{
    struct trigger_results results = {.done = 0, .aborted = 0};
    struct nl_msg *msg;
    struct nl_cb *cb;
    struct nl_msg *ssids_to_scan;
    int err;
    int ret;
    int mcid = genl_ctrl_resolve_grp(socket, "nl80211", "scan");

    if (mcid >= 0)
        nl_socket_add_membership(socket, mcid);

    msg = nlmsg_alloc();
    if (!msg)
    {
        fprintf(stderr, "failed to allocate netlink message\n");
        return -ENOMEM;
    }

    ssids_to_scan = nlmsg_alloc();
    if (!ssids_to_scan)
    {
        fprintf(stderr, "failed to allocate scan ssid message\n");
        nlmsg_free(msg);
        return -ENOMEM;
    }

    cb = nl_cb_alloc(NL_CB_DEFAULT);
    if (!cb)
    {
        fprintf(stderr, "failed to allocate netlink callbacks\n");
        nlmsg_free(msg);
        nlmsg_free(ssids_to_scan);
        return -ENOMEM;
    }

    genlmsg_put(msg, 0, 0, driver_id, 0, 0, NL80211_CMD_TRIGGER_SCAN, 0);
    nla_put_u32(msg, NL80211_ATTR_IFINDEX, if_index);
    nla_put_u32(msg, NL80211_ATTR_SCAN_FLAGS, NL80211_SCAN_FLAG_FLUSH);

    nla_put(ssids_to_scan, 1, 0, "");
    nla_put_nested(msg, NL80211_ATTR_SCAN_SSIDS, ssids_to_scan);
    nlmsg_free(ssids_to_scan);

    nl_cb_set(cb, NL_CB_VALID, NL_CB_CUSTOM, callback_trigger, &results);
    nl_cb_err(cb, NL_CB_CUSTOM, error_handler, &err);
    nl_cb_set(cb, NL_CB_FINISH, NL_CB_CUSTOM, finish_handler, &err);
    nl_cb_set(cb, NL_CB_ACK, NL_CB_CUSTOM, ack_handler, &err);
    nl_cb_set(cb, NL_CB_SEQ_CHECK, NL_CB_CUSTOM, no_seq_check, NULL);

    err = 1;
    ret = nl_send_auto(socket, msg);

    if (ret < 0)
    {
        fprintf(stderr, "nl_send_auto failed: %d (%s)\n", ret, nl_geterror(-ret));
        nlmsg_free(msg);
        nl_cb_put(cb);
        return ret;
    }

    while (err > 0)
        ret = nl_recvmsgs(socket, cb);

    if (ret < 0)
    {
        fprintf(stderr, "nl_recvmsgs failed: %d (%s)\n", ret, nl_geterror(-ret));
        nlmsg_free(msg);
        nl_cb_put(cb);
        return ret;
    }

    while (!results.done)
        nl_recvmsgs(socket, cb);

    if (results.aborted)
    {
        fprintf(stderr, "kernel aborted scan\n");
        nlmsg_free(msg);
        nl_cb_put(cb);
        return 1;
    }

    nlmsg_free(msg);
    nl_cb_put(cb);

    if (mcid >= 0)
        nl_socket_drop_membership(socket, mcid);

    return 0;
}

void perform_scan(struct nl_sock *socket, int if_index, int driver_id)
{
    result_count = 0;

    struct nl_msg *msg = nlmsg_alloc();
    if (!msg)
    {
        fprintf(stderr, "failed to allocate scan dump message\n");
        return;
    }

    genlmsg_put(msg, 0, 0, driver_id, 0, NLM_F_DUMP, NL80211_CMD_GET_SCAN, 0);
    nla_put_u32(msg, NL80211_ATTR_IFINDEX, if_index);

    nl_socket_modify_cb(socket, NL_CB_VALID, NL_CB_CUSTOM, callback_dump, NULL);

    int ret = nl_send_auto(socket, msg);
    if (ret < 0)
    {
        fprintf(stderr, "scan dump send failed: %d (%s)\n", ret, nl_geterror(-ret));
        nlmsg_free(msg);
        return;
    }

    ret = nl_recvmsgs_default(socket);
    if (ret < 0)
    {
        fprintf(stderr, "scan dump receive failed: %d (%s)\n", ret, nl_geterror(-ret));
    }

    nlmsg_free(msg);
}

void metrics(void)
{
    printf("{\"metrics\":[");

    for (int i = 0; i < result_count; i++)
    {
        char ssid[80];
        char bssid[40];

        json_escape(dataResult[i].ssid, ssid, sizeof(ssid));
        json_escape(dataResult[i].bssid, bssid, sizeof(bssid));

        double signal_dbm = dataResult[i].mbm / 100.0;

        printf(
            "{\"name\":\"beacon_wifi_scan_signal_dbm\","
            "\"kind\":\"gauge\","
            "\"value\":%.2f,"
            "\"labels\":{\"ssid\":\"%s\",\"bssid\":\"%s\",\"frequency\":\"%d\"}},"
            "{\"name\":\"beacon_wifi_scan_frequency_mhz\","
            "\"kind\":\"gauge\","
            "\"value\":%d,"
            "\"labels\":{\"ssid\":\"%s\",\"bssid\":\"%s\"}},"
            "{\"name\":\"beacon_wifi_scan_seen_ms_ago\","
            "\"kind\":\"gauge\","
            "\"value\":%d,"
            "\"labels\":{\"ssid\":\"%s\",\"bssid\":\"%s\"}}",
            signal_dbm,
            ssid,
            bssid,
            dataResult[i].frequency,
            dataResult[i].frequency,
            ssid,
            bssid,
            dataResult[i].msAgo,
            ssid,
            bssid);

        if (i < result_count - 1)
            printf(",");
    }

    printf("]}\n");
}

int main(int argc, char **argv)
{
    const char *iface = "wlan0";

    if (argc > 1 && argv[1] && argv[1][0] != '\0')
        iface = argv[1];

    int if_index = if_nametoindex(iface);
    if (if_index == 0)
    {
        fprintf(stderr, "interface not found: %s\n", iface);
        printf("{\"metrics\":[]}\n");
        return 0;
    }

    struct nl_sock *socket = nl_socket_alloc();
    if (!socket)
    {
        fprintf(stderr, "failed to allocate netlink socket\n");
        printf("{\"metrics\":[]}\n");
        return 0;
    }

    if (genl_connect(socket) != 0)
    {
        fprintf(stderr, "failed to connect generic netlink socket\n");
        nl_socket_free(socket);
        printf("{\"metrics\":[]}\n");
        return 0;
    }

    int driver_id = genl_ctrl_resolve(socket, "nl80211");
    if (driver_id < 0)
    {
        fprintf(stderr, "failed to resolve nl80211\n");
        nl_socket_free(socket);
        printf("{\"metrics\":[]}\n");
        return 0;
    }

    int err = do_scan_trigger(socket, if_index, driver_id);
    if (err != 0)
    {
        fprintf(stderr, "do_scan_trigger failed with %d\n", err);
        nl_socket_free(socket);
        printf("{\"metrics\":[]}\n");
        return 0;
    }

    perform_scan(socket, if_index, driver_id);
    metrics();

    nl_socket_free(socket);
    return 0;
}
