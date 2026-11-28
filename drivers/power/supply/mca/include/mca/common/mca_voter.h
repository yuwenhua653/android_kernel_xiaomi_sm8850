#ifndef _MCA_COMMON_MCA_VOTER_H_
#define _MCA_COMMON_MCA_VOTER_H_

#include <linux/types.h>

struct mca_votable;

enum mca_votable_type {
	MCA_VOTE_MIN,
	MCA_VOTE_MAX,
	MCA_VOTE_OR,
	MCA_VOTE_AND,
	NUM_VOTABLE_TYPES,
};

void mca_lock_votable(struct mca_votable *votable);
void mca_unlock_votable(struct mca_votable *votable);
bool mca_is_override_vote_enabled_locked(struct mca_votable *votable);
bool mca_is_override_vote_enabled(struct mca_votable *votable);
bool mca_is_client_vote_enabled_locked(struct mca_votable *votable,
				       const char *client_str);
bool mca_is_client_vote_enabled(struct mca_votable *votable,
				const char *client_str);
int mca_get_client_vote_locked(struct mca_votable *votable,
			       const char *client_str);
int mca_get_client_vote(struct mca_votable *votable, const char *client_str);
int mca_get_effective_result_locked(struct mca_votable *votable);
int mca_get_effective_result(struct mca_votable *votable);
const char *mca_get_effective_client_locked(struct mca_votable *votable);
const char *mca_get_effective_client(struct mca_votable *votable);
int mca_vote(struct mca_votable *votable, const char *client_str, bool enabled,
	     int val);
int mca_vote_override(struct mca_votable *votable, const char *override_client,
		      bool enabled, int val);
int mca_rerun_election(struct mca_votable *votable);
struct mca_votable *mca_find_votable(const char *name);
struct mca_votable *mca_create_votable(
	const char *name, int votable_type,
	int (*callback)(struct mca_votable *votable, void *data,
			int effective_result, const char *effective_client),
	int default_value, void *data);
/* Owned slots retain their address and client votes across provider removal.
 * Creation attaches one provider and does not call hardware. Same-name/type/
 * default reattachment is allowed only after detach; replay with rerun_election
 * or a fresh vote after the provider is ready. A detached slot rejects writes with -ENODEV.
 * Detach synchronously drains callbacks, then the owner may free its data.
 * Never create/detach from callbacks or while holding locks they acquire.
 * Do not destroy an owned slot: consumers may cache find_votable pointers.
 * This contract does not add lifetime protection to legacy-created voters.
 */
struct mca_votable *mca_create_owned_votable(
	const char *name, int votable_type,
	int (*callback)(struct mca_votable *, void *, int, const char *),
	int default_value, void *data);
int mca_detach_owned_votable(struct mca_votable *votable, void *data);
void mca_destroy_votable(struct mca_votable *votable);

#endif /* _MCA_COMMON_MCA_VOTER_H_ */
