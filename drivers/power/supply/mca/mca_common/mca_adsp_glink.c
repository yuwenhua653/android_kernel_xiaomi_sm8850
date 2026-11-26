#include <linux/module.h>
#include <linux/init.h>
#include <linux/slab.h>
#include <linux/device.h>
#include <linux/platform_device.h>
#include <linux/mutex.h>
#include <linux/srcu.h>
#include <linux/spinlock.h>
#include <linux/completion.h>
#include <linux/workqueue.h>
#include <linux/list.h>
#include <linux/string.h>
#include <linux/err.h>
#include <linux/mod_devicetable.h>
#include <linux/of_device.h>
#include <linux/soc/qcom/qti_pmic_glink.h>
#include <mca/common/mca_log.h>
#include <mca/common/mca_adsp_glink.h>

#ifndef MCA_LOG_TAG
#define MCA_LOG_TAG "mca_adsp_glink"
#endif

#define MCA_ADSP_GLINK_OWNER 0x800A
#define MCA_ADSP_GLINK_QBG_OWNER 0x8009
#define MCA_ADSP_GLINK_MSG_REQ 1 /* hdr.type: request/response */
#define MCA_ADSP_GLINK_MSG_NOTIFY 2 /* hdr.type: async notification */
#define MCA_ADSP_GLINK_OPCODE_READ 1
#define MCA_ADSP_GLINK_OPCODE_WRITE 2
#define MCA_ADSP_PROP_DATA_LEN 256
#define MCA_ADSP_GLINK_TIMEOUT_MS 250

struct mca_adsp_glink_req_msg {
	struct pmic_glink_hdr hdr;
	u32 property_id;
	u32 seq;
	u8 data[MCA_ADSP_PROP_DATA_LEN];
} __packed;

struct mca_adsp_glink_resp_msg {
	struct pmic_glink_hdr hdr;
	u32 property_id;
	u32 retcode;
	u32 seq;
	u8 data[MCA_ADSP_PROP_DATA_LEN];
} __packed;

struct mca_adsp_glink_notify_msg {
	struct pmic_glink_hdr hdr;
	u32 property_id;
	u8 data[MCA_ADSP_PROP_DATA_LEN];
} __packed;

struct mca_adsp_glink_dev {
	struct device *dev;
	struct pmic_glink_client *client;
	struct mutex rw_lock;
	/* Serialize state delivery against queued UP work and removal. */
	struct mutex state_lock;
	bool stopping;
	struct completion ack;
	spinlock_t pending_lock;
	bool pending;
	u32 cur_owner;
	u32 cur_opcode;
	u32 cur_seq;
	int glink_state;
	struct work_struct sync_work;
	u32 cur_property_id;
	int retcode;
	u32 remote_retcode;
	u32 seq;
	u8 read_buf[MCA_ADSP_PROP_DATA_LEN];
};

struct mca_adsp_ops_node {
	struct list_head node;
	void *priv;
	struct mca_adsp_glink_ops *ops;
};

static struct mca_adsp_glink_dev __rcu *g_mca_adsp_glink;
static DEFINE_MUTEX(g_mca_adsp_probe_lock);
static DEFINE_MUTEX(g_mca_adsp_ops_lock);
DEFINE_STATIC_SRCU(g_mca_adsp_srcu);
DEFINE_STATIC_SRCU(g_mca_adsp_ops_srcu);
static LIST_HEAD(g_mca_adsp_glink_ops_head);
static LIST_HEAD(g_mca_adsp_glink_qbg_ops_head);

/* rw_lock serializes senders; pending_lock also covers the RX callback. */
static int mca_adsp_glink_begin_request(struct mca_adsp_glink_dev *mca,
				       const struct mca_adsp_glink_req_msg *msg)
{
	unsigned long flags;
	int ret = 0;

	spin_lock_irqsave(&mca->pending_lock, flags);
	if (mca->stopping || mca->glink_state != PMIC_GLINK_STATE_UP) {
		ret = -ENOTCONN;
		goto out;
	}
	reinit_completion(&mca->ack);
	mca->retcode = 0;
	mca->remote_retcode = 0;
	memset(mca->read_buf, 0, sizeof(mca->read_buf));
	mca->cur_property_id = msg->property_id;
	mca->cur_owner = msg->hdr.owner;
	mca->cur_opcode = msg->hdr.opcode;
	mca->cur_seq = msg->seq;
	mca->pending = true;
out:
	spin_unlock_irqrestore(&mca->pending_lock, flags);
	return ret;
}

static void mca_adsp_glink_end_request(struct mca_adsp_glink_dev *mca)
{
	unsigned long flags;

	spin_lock_irqsave(&mca->pending_lock, flags);
	mca->pending = false;
	mca->cur_property_id = 0xffffffff;
	spin_unlock_irqrestore(&mca->pending_lock, flags);
}

int mca_adsp_glink_write_prop(int prop_id, void *value, size_t size)
{
	struct mca_adsp_glink_dev *mca;
	struct mca_adsp_glink_req_msg msg = { 0 };
	int ret, idx;

	if (!value || !size || size >= MCA_ADSP_PROP_DATA_LEN)
		return -EINVAL;

	idx = srcu_read_lock(&g_mca_adsp_srcu);
	mca = srcu_dereference(g_mca_adsp_glink, &g_mca_adsp_srcu);
	if (!mca) {
		ret = -ENODEV;
		goto unlock_srcu;
	}
	mutex_lock(&mca->rw_lock);
	mca->seq++;
	msg.hdr.owner = MCA_ADSP_GLINK_OWNER;
	msg.hdr.type = MCA_ADSP_GLINK_MSG_REQ;
	msg.hdr.opcode = MCA_ADSP_GLINK_OPCODE_WRITE;
	msg.property_id = prop_id;
	msg.seq = mca->seq;
	memcpy(msg.data, value, size);

	ret = mca_adsp_glink_begin_request(mca, &msg);
	if (ret) {
		mca_log_err("glink state is down\n");
		goto out;
	}
	ret = pmic_glink_write(mca->client, &msg, sizeof(msg));
	if (ret == 0) {
		if (wait_for_completion_timeout(
			    &mca->ack,
			    msecs_to_jiffies(MCA_ADSP_GLINK_TIMEOUT_MS)) == 0) {
			mca_log_err("timed out sending message, prop_id: %d\n",
				    mca->cur_property_id);
			ret = -ETIMEDOUT;
		} else {
			ret = mca->retcode;
		}
	}
out:
	mca_adsp_glink_end_request(mca);
	mutex_unlock(&mca->rw_lock);
unlock_srcu:
	srcu_read_unlock(&g_mca_adsp_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_adsp_glink_write_prop);

int mca_adsp_glink_read_prop(int prop_id, void *value, size_t size)
{
	struct mca_adsp_glink_dev *mca;
	struct mca_adsp_glink_req_msg msg = { 0 };
	int ret, idx;

	if (!value || !size || size >= MCA_ADSP_PROP_DATA_LEN)
		return -EINVAL;

	idx = srcu_read_lock(&g_mca_adsp_srcu);
	mca = srcu_dereference(g_mca_adsp_glink, &g_mca_adsp_srcu);
	if (!mca) {
		ret = -ENODEV;
		goto unlock_srcu;
	}
	mutex_lock(&mca->rw_lock);
	mca->seq++;
	msg.hdr.owner = MCA_ADSP_GLINK_OWNER;
	msg.hdr.type = MCA_ADSP_GLINK_MSG_REQ;
	msg.hdr.opcode = MCA_ADSP_GLINK_OPCODE_READ;
	msg.property_id = prop_id;
	msg.seq = mca->seq;

	ret = mca_adsp_glink_begin_request(mca, &msg);
	if (ret) {
		mca_log_err("glink state is down\n");
		goto out;
	}
	ret = pmic_glink_write(mca->client, &msg, sizeof(msg));
	if (ret == 0) {
		if (wait_for_completion_timeout(
			    &mca->ack,
			    msecs_to_jiffies(MCA_ADSP_GLINK_TIMEOUT_MS)) == 0) {
			mca_log_err("timed out sending message, prop_id: %d\n",
				    mca->cur_property_id);
			ret = -ETIMEDOUT;
		} else {
			ret = mca->retcode;
			if (ret == 0) {
				memcpy(value, mca->read_buf, size);
				memset(mca->read_buf, 0,
				       MCA_ADSP_PROP_DATA_LEN);
			}
		}
	}
out:
	mca_adsp_glink_end_request(mca);
	mutex_unlock(&mca->rw_lock);
unlock_srcu:
	srcu_read_unlock(&g_mca_adsp_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_adsp_glink_read_prop);

/* Call register/unregister outside any MCA ops callback. */
static int mca_adsp_glink_add_ops(struct list_head *head,
				  struct mca_adsp_glink_ops *ops, void *priv)
{
	struct mca_adsp_ops_node *n, *pos;

	if (!ops)
		return -EINVAL;
	n = kzalloc(sizeof(*n), GFP_KERNEL);
	if (!n)
		return -ENOMEM;
	n->ops = ops;
	n->priv = priv;
	mutex_lock(&g_mca_adsp_ops_lock);
	list_for_each_entry(pos, head, node) {
		if (pos->ops == ops && pos->priv == priv) {
			mutex_unlock(&g_mca_adsp_ops_lock);
			kfree(n);
			return -EEXIST;
		}
	}
	list_add_rcu(&n->node, head);
	mutex_unlock(&g_mca_adsp_ops_lock);
	return 0;
}

static void mca_adsp_glink_del_ops(struct list_head *head,
				   struct mca_adsp_glink_ops *ops, void *priv)
{
	struct mca_adsp_ops_node *n, *old = NULL;

	mutex_lock(&g_mca_adsp_ops_lock);
	list_for_each_entry(n, head, node) {
		if (n->ops == ops && n->priv == priv) {
			list_del_rcu(&n->node);
			old = n;
			break;
		}
	}
	mutex_unlock(&g_mca_adsp_ops_lock);
	/* Drain even if another unregister already removed this registration. */
	synchronize_srcu(&g_mca_adsp_ops_srcu);
	kfree(old);
}

int mca_adsp_glink_resister_ops(struct mca_adsp_glink_ops *ops, void *priv)
{
	return mca_adsp_glink_add_ops(&g_mca_adsp_glink_ops_head, ops, priv);
}
EXPORT_SYMBOL(mca_adsp_glink_resister_ops);

void mca_adsp_glink_unregister_ops(struct mca_adsp_glink_ops *ops, void *priv)
{
	mca_adsp_glink_del_ops(&g_mca_adsp_glink_ops_head, ops, priv);
}
EXPORT_SYMBOL_GPL(mca_adsp_glink_unregister_ops);

int mca_adsp_glink_qbg_write_prop(int prop_id, void *value, size_t size)
{
	struct mca_adsp_glink_dev *mca;
	struct mca_adsp_glink_req_msg msg = { 0 };
	int ret, idx;

	if (!value || !size || size >= MCA_ADSP_PROP_DATA_LEN)
		return -EINVAL;

	idx = srcu_read_lock(&g_mca_adsp_srcu);
	mca = srcu_dereference(g_mca_adsp_glink, &g_mca_adsp_srcu);
	if (!mca) {
		ret = -ENODEV;
		goto unlock_srcu;
	}
	mutex_lock(&mca->rw_lock);
	mca->seq++;
	msg.hdr.owner = MCA_ADSP_GLINK_QBG_OWNER;
	msg.hdr.type = MCA_ADSP_GLINK_MSG_REQ;
	msg.hdr.opcode = MCA_ADSP_GLINK_OPCODE_WRITE;
	msg.property_id = prop_id;
	msg.seq = mca->seq;
	memcpy(msg.data, value, size);

	ret = mca_adsp_glink_begin_request(mca, &msg);
	if (ret) {
		mca_log_err("glink state is down\n");
		goto out;
	}
	ret = pmic_glink_write(mca->client, &msg, sizeof(msg));
	if (ret == 0) {
		if (wait_for_completion_timeout(
			    &mca->ack,
			    msecs_to_jiffies(MCA_ADSP_GLINK_TIMEOUT_MS)) == 0) {
			mca_log_err("timed out sending message, prop_id: %d\n",
				    mca->cur_property_id);
			ret = -ETIMEDOUT;
		} else {
			ret = mca->retcode;
		}
	}
out:
	mca_adsp_glink_end_request(mca);
	mutex_unlock(&mca->rw_lock);
unlock_srcu:
	srcu_read_unlock(&g_mca_adsp_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_adsp_glink_qbg_write_prop);

int mca_adsp_glink_qbg_read_prop(int prop_id, void *value, size_t size)
{
	struct mca_adsp_glink_dev *mca;
	struct mca_adsp_glink_req_msg msg = { 0 };
	int ret, idx;

	if (!value || !size || size >= MCA_ADSP_PROP_DATA_LEN)
		return -EINVAL;

	idx = srcu_read_lock(&g_mca_adsp_srcu);
	mca = srcu_dereference(g_mca_adsp_glink, &g_mca_adsp_srcu);
	if (!mca) {
		ret = -ENODEV;
		goto unlock_srcu;
	}
	mutex_lock(&mca->rw_lock);
	mca->seq++;
	msg.hdr.owner = MCA_ADSP_GLINK_QBG_OWNER;
	msg.hdr.type = MCA_ADSP_GLINK_MSG_REQ;
	msg.hdr.opcode = MCA_ADSP_GLINK_OPCODE_READ;
	msg.property_id = prop_id;
	msg.seq = mca->seq;

	ret = mca_adsp_glink_begin_request(mca, &msg);
	if (ret) {
		mca_log_err("glink state is down\n");
		goto out;
	}
	ret = pmic_glink_write(mca->client, &msg, sizeof(msg));
	if (ret == 0) {
		if (wait_for_completion_timeout(
			    &mca->ack,
			    msecs_to_jiffies(MCA_ADSP_GLINK_TIMEOUT_MS)) == 0) {
			mca_log_err("timed out sending message, prop_id: %d\n",
				    mca->cur_property_id);
			ret = -ETIMEDOUT;
		} else {
			ret = mca->retcode;
			if (ret == 0) {
				memcpy(value, mca->read_buf, size);
				memset(mca->read_buf, 0,
				       MCA_ADSP_PROP_DATA_LEN);
			}
		}
	}
out:
	mca_adsp_glink_end_request(mca);
	mutex_unlock(&mca->rw_lock);
unlock_srcu:
	srcu_read_unlock(&g_mca_adsp_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_adsp_glink_qbg_read_prop);

int mca_adsp_glink_qbg_resister_ops(struct mca_adsp_glink_ops *ops, void *priv)
{
	return mca_adsp_glink_add_ops(&g_mca_adsp_glink_qbg_ops_head, ops, priv);
}
EXPORT_SYMBOL(mca_adsp_glink_qbg_resister_ops);

void mca_adsp_glink_qbg_unregister_ops(struct mca_adsp_glink_ops *ops, void *priv)
{
	mca_adsp_glink_del_ops(&g_mca_adsp_glink_qbg_ops_head, ops, priv);
}
EXPORT_SYMBOL_GPL(mca_adsp_glink_qbg_unregister_ops);

static int
mca_adsp_glink_handle_notification(struct mca_adsp_glink_dev *mca,
				   struct mca_adsp_glink_notify_msg *msg)
{
	struct mca_adsp_ops_node *n;
	struct list_head *head;
	int idx;

	head = (msg->hdr.owner == MCA_ADSP_GLINK_QBG_OWNER) ?
		       &g_mca_adsp_glink_qbg_ops_head :
		       &g_mca_adsp_glink_ops_head;

	mca_log_info("mca_adsp receive notification %d, owner %d\n",
		     msg->property_id, msg->hdr.owner);
	idx = srcu_read_lock(&g_mca_adsp_ops_srcu);
	list_for_each_entry_rcu(n, head, node,
				srcu_read_lock_held(&g_mca_adsp_ops_srcu)) {
		if (n->ops && n->ops->notification)
			n->ops->notification(msg->property_id, msg->data,
					     MCA_ADSP_PROP_DATA_LEN, n->priv);
	}
	srcu_read_unlock(&g_mca_adsp_ops_srcu, idx);
	return 0;
}

static int mca_adsp_glink_handle_message(struct mca_adsp_glink_dev *mca,
					 struct mca_adsp_glink_resp_msg *msg,
					 size_t len)
{
	unsigned long flags;

	/* Accept only the fixed response format defined above. */
	if (len != sizeof(*msg))
		return 0;

	spin_lock_irqsave(&mca->pending_lock, flags);
	if (!mca->pending || msg->hdr.type != MCA_ADSP_GLINK_MSG_REQ ||
	    msg->hdr.owner != mca->cur_owner ||
	    msg->hdr.opcode != mca->cur_opcode ||
	    msg->property_id != mca->cur_property_id ||
	    msg->seq != mca->cur_seq)
		goto out;

	/* The wire status is unsigned; only zero denotes a successful reply. */
	mca->remote_retcode = msg->retcode;
	mca->retcode = msg->retcode ? -EREMOTEIO : 0;
	if (!msg->retcode && msg->hdr.opcode == MCA_ADSP_GLINK_OPCODE_READ)
		memcpy(mca->read_buf, msg->data, MCA_ADSP_PROP_DATA_LEN);
	mca->pending = false;
	complete(&mca->ack);
out:
	spin_unlock_irqrestore(&mca->pending_lock, flags);
	return 0;
}

static int mca_adsp_glink_callback(void *priv, void *data, size_t len)
{
	struct mca_adsp_glink_dev *mca = priv;
	struct pmic_glink_hdr hdr;

	if (!mca || !data || len < sizeof(hdr))
		return 0;

	memcpy(&hdr, data, sizeof(hdr));
	if (hdr.owner != MCA_ADSP_GLINK_OWNER &&
	    hdr.owner != MCA_ADSP_GLINK_QBG_OWNER)
		return 0;

	if (hdr.type == MCA_ADSP_GLINK_MSG_NOTIFY) {
		if (len != sizeof(struct mca_adsp_glink_notify_msg))
			return 0;
		/* No notification opcode value is defined by this wire contract. */
		return mca_adsp_glink_handle_notification(mca, data);
	}

	if (hdr.type != MCA_ADSP_GLINK_MSG_REQ ||
	    (hdr.opcode != MCA_ADSP_GLINK_OPCODE_READ &&
	     hdr.opcode != MCA_ADSP_GLINK_OPCODE_WRITE))
		return 0;

	return mca_adsp_glink_handle_message(mca, data, len);
}

static void mca_adsp_glink_notify_state(enum pmic_glink_state state)
{
	struct mca_adsp_ops_node *n;
	struct list_head *heads[] = {
		&g_mca_adsp_glink_ops_head, &g_mca_adsp_glink_qbg_ops_head,
	};
	int i, idx;

	idx = srcu_read_lock(&g_mca_adsp_ops_srcu);
	for (i = 0; i < ARRAY_SIZE(heads); i++) {
		list_for_each_entry_rcu(n, heads[i], node,
					srcu_read_lock_held(&g_mca_adsp_ops_srcu)) {
			if (state == PMIC_GLINK_STATE_UP) {
				if (n->ops->glink_state_up)
					n->ops->glink_state_up(n->priv);
			} else if (n->ops->glink_state_down) {
				n->ops->glink_state_down(n->priv);
			}
		}
	}
	srcu_read_unlock(&g_mca_adsp_ops_srcu, idx);
}

static void mca_adsp_glink_sync_work(struct work_struct *work)
{
	struct mca_adsp_glink_dev *mca =
		container_of(work, struct mca_adsp_glink_dev, sync_work);

	/* A queued UP must not be delivered after a newer DOWN notification. */
	mutex_lock(&mca->state_lock);
	if (!mca->stopping && mca->glink_state == PMIC_GLINK_STATE_UP)
		mca_adsp_glink_notify_state(PMIC_GLINK_STATE_UP);
	mutex_unlock(&mca->state_lock);
}

static void mca_adsp_glink_state_cb(void *priv, enum pmic_glink_state state)
{
	struct mca_adsp_glink_dev *mca = priv;
	unsigned long flags;

	mutex_lock(&mca->state_lock);
	spin_lock_irqsave(&mca->pending_lock, flags);
	if (mca->stopping) {
		spin_unlock_irqrestore(&mca->pending_lock, flags);
		mutex_unlock(&mca->state_lock);
		return;
	}
	mca->glink_state = state;
	if (state != PMIC_GLINK_STATE_UP && mca->pending) {
		mca->pending = false;
		mca->retcode = -ENOTCONN;
		complete(&mca->ack);
	}
	spin_unlock_irqrestore(&mca->pending_lock, flags);
	if (state == PMIC_GLINK_STATE_UP)
		queue_work(system_wq, &mca->sync_work);
	else
		mca_adsp_glink_notify_state(state);
	mutex_unlock(&mca->state_lock);
}

static int mca_adsp_glink_probe(struct platform_device *pdev)
{
	struct mca_adsp_glink_dev *mca;
	struct pmic_glink_client_data client_data = { 0 };
	int ret;

	mca = devm_kzalloc(&pdev->dev, sizeof(*mca), GFP_KERNEL);
	if (!mca)
		return -ENOMEM;

	mca->dev = &pdev->dev;
	mca->cur_property_id = 0xffffffff;
	mutex_init(&mca->rw_lock);
	mutex_init(&mca->state_lock);
	spin_lock_init(&mca->pending_lock);
	init_completion(&mca->ack);
	mca->glink_state = PMIC_GLINK_STATE_UP;
	INIT_WORK(&mca->sync_work, mca_adsp_glink_sync_work);

	client_data.name = "mca_adap_glink";
	client_data.id = MCA_ADSP_GLINK_OWNER;
	client_data.priv = mca;
	client_data.msg_cb = mca_adsp_glink_callback;
	client_data.state_cb = mca_adsp_glink_state_cb;

	mutex_lock(&g_mca_adsp_probe_lock);
	if (rcu_access_pointer(g_mca_adsp_glink)) {
		ret = -EBUSY;
		goto unlock_probe;
	}
	mca->client = pmic_glink_register_client(&pdev->dev, &client_data);
	if (IS_ERR(mca->client)) {
		ret = PTR_ERR(mca->client);
		if (ret != -EPROBE_DEFER)
			mca_log_err("Error in registering with pmic_glink %d\n", ret);
		goto unlock_probe;
	}

	platform_set_drvdata(pdev, mca);
	rcu_assign_pointer(g_mca_adsp_glink, mca);
	/* Existing consumers must resynchronize after a provider rebind. */
	queue_work(system_wq, &mca->sync_work);
	mca_log_info("probe ok\n");
	ret = 0;
unlock_probe:
	mutex_unlock(&g_mca_adsp_probe_lock);
	return ret;
}

static void mca_adsp_glink_remove(struct platform_device *pdev)
{
	struct mca_adsp_glink_dev *mca = platform_get_drvdata(pdev);
	unsigned long flags;

	mutex_lock(&g_mca_adsp_probe_lock);
	RCU_INIT_POINTER(g_mca_adsp_glink, NULL);
	mutex_lock(&mca->state_lock);
	spin_lock_irqsave(&mca->pending_lock, flags);
	mca->stopping = true;
	mca->glink_state = PMIC_GLINK_STATE_DOWN;
	if (mca->pending) {
		mca->pending = false;
		mca->retcode = -ENODEV;
		complete(&mca->ack);
	}
	spin_unlock_irqrestore(&mca->pending_lock, flags);
	mca_adsp_glink_notify_state(PMIC_GLINK_STATE_DOWN);
	mutex_unlock(&mca->state_lock);
	/* Drain API users before freeing their transport handle. */
	synchronize_srcu(&g_mca_adsp_srcu);
	pmic_glink_unregister_client_sync(mca->client);
	/* Unregister drains callbacks, including any last work submission. */
	cancel_work_sync(&mca->sync_work);
	mutex_unlock(&g_mca_adsp_probe_lock);
}

static const struct of_device_id mca_adsp_match_table[] = {
	{ .compatible = "mca,adsp_glink" },
	{},
};

static struct platform_driver mca_adsp_driver = {
	.driver = {
		.name = "mca_adsp_glink",
		.of_match_table = mca_adsp_match_table,
	},
	.probe = mca_adsp_glink_probe,
	.remove = mca_adsp_glink_remove,
};
module_platform_driver(mca_adsp_driver);

MODULE_DESCRIPTION("mca glink driver");
MODULE_AUTHOR("liyuze1@xiaomi.com");
MODULE_LICENSE("GPL v2");
