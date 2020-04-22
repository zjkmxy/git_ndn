# GitSync Design Document

## Basic Ideas
- Everything is stored in git repos.
- Non-code branches contain only `.tlv` files, TLV-encoded.
- All `.tlv` file should be signed, containing a time-stamp.
  1. `git diff` can handle binary files if there is a converter which translates it into ASCII. Therefore, it does not impede readability.
  1. Every new `.tlv` file fetched from the network should be verified.
- Code branch should be protected by a meta branch, doing custodian things.
  1. One reason is that git signed commit is not easy to handle.
  1. Non-append-only branch is not easy to handle, so we can restrict security on append-only branches.
  1. Also, this keeps the history of reverting branches.
- Every non-code branches uses the same structure to store configurations.
- `admin` group has access to everything without configuration.
- In this doc, `<NAME>` means a GenericNameComponent. `[PREFIX]` means the prefix of the namespace owned by this system.
- Due to git's pack policies, git will pack up files if there are too many in a folder.
  Thus, sometimes we use the first 2 characters to group files. This is written as `<__>`.
  E.g. `refs/users/xi/xinyuma` matches with `refs/users/<__>/<uid>`.

## Project Common Refs
### Configuration `refs/meta/config`
- `project.tlv`
```text
ProjectConfig
  pid
  description
  inherit_from
  sync_interval
  ref_config*
  label*
  (other_options)

RefConfig
  ref_name
  operation_rule*
  label_rule*

LabelConfig
  name
  function
  default_value
  label_value*

OperationRule
  operation
  access
  group_gid*
  user_uid*

LabelRule
  label
  min_value
  max_value
  group_gid*

LabelValue
  number
  description
```
Access can be (ALLOW, DENY).
Function can be (MaxWithBlock, AnyWithBlock, MaxNoBlock, NoBlock)

### Local info `refs/local/*`
Not public. Only used to store local info related to a specific project.

## Users Repo `All-Users.git`
### User `refs/users/<__>/<uid>`
How users git their UID is out sourced to certificate issurance system.
`admin` user under `admin` group holds the trust anchor.
This account should be avoided in normal operations, and only `admin` group can modify it.

- `account.tlv`
```text
AccountConfig
  uid
  full_name
  email
```
- `KEY/<key-id>.cert`
A file holding an NDN certificate.
Key name should be `[PREFIX]/users/<uid>/KEY/<key-id>`
`<key-id>` should be eocnded by hex.

- `KEY/<key-id>.revoke.tlv`
Only exists when a key is revoked.
We do not assume the clock is synced, so we include current HEADs of every branch to indicate when it is revoked.
```text
Revoke
  key_id
  revoke_time
  current_head*
```

### Group `refs/groups/<__>/<gid>`
- `group.tlv`
```text
GroupConfig
  gid
  full_name
  owner
  member_uid*
```
A group has a single owner user.
This may not scale well, but let us slow start.

## Projects Catalog Repo `All-Projects.git`
### Projects catalog `refs/projects/catalog`
- `projects.tlv`
Plain text, containing a list of projects.
Everyone can create new projects, but we need a catalog to avoid conflict.
A peer can choose to track a project or not.
However, projects cannot be removed.

### Security template `refs/meta/config`
- `project.tlv`
This is used as a template for all projects.

## Code Repo `<PID>`
`<PID>` can contain a "/" inside.

### Branch catalog `refs/meta/catalog`
- `branches.tlv`
Plain text, containing a list of code branches.
Everyone can create new branches, but we need a catalog to avoid conflict.
Branches cannot be removed.
*How can we rename or remove a branch when necessary?*

- `changes.tlv`
Plain text, containing a list of Change-IDs.

### Code branch `refs/heads/<code-branch>`
Code branch.
Also, in access rules, this is used to set the direct access priviledge.
Do not sync this branch; sync `bmeta` instead.

### Code branch meta branch `refs/bmeta/<code-branch>`
- `head.tlv`
```text
HeadRef
  head
  change-id
  change-id-meta-commit
```
Contains the current HEAD of `refs/heads/<code-branch>`.
Must be signed.
As `refs/bmeta/<code-branch>` itself has commit history, there is no need to store historical HEADs.
This branch cannot be reverted / rebased.
Conflicts cannot be auto resolved; a user needs to force-push.
Last 2 components are optional and only used if there exists code review.

### Virtual branch `refs/for/<code-branch>`
Not exists physically.
Used to propose changes, and specify the priviledge for proposing changes.

### Patch-set branch `refs/changes/<__>/<Change-ID>/<PatchSet>`
Code branch. Immutable.

### Code review branch `refs/changes/<__>/<Change-ID>/meta`
- `change.tlv`
```text
ChangeMeta
  change-id
  status
  patch_set
  subject
```
Status can be (NEW, MERGED, ABANDONED).

- `<PatchSet>/votes/<reviewer-uid>.tlv`
```text
Vote
  label
  value
```

- `<PatchSet>/comments/<comment-id>.tlv`
```text
Comment
  comment_id
  filename
  line_nbr
  author
  written_on
  message
  rev_id
  unsolved
```
CommentId is some hash name.
Filename is the file commented like "README.md". "/COMMIT_MSG" means the commit message.
LineNbr is the line number (1-based) to which the comment refers, or 0 for a file comment.
rev_id is the commit of the PatchSet (SHA-1).
unsolved can be (true, false). A thread is decided by the last post.

## GitSync Namespace
- `[PREFIX]/users/<uid>`: User info for a specific user.
  - `./KEY/<key-id>`: User's certificate.
- `[PREFIX]/project/<PID>`: Used to fetch an object/ref under a specific project.
  - `./objects/<sha-1>/<seg=i>`: A (segmented) git object.
  - `./refs/<branch-name>`: Interests to learn the head of a branch.
    - `./<v=timestamp>`: Data containing the current HEAD.
  - `./sync/<params-digest>`: Sync Interest.

## Sync Protocol

### When to advertise
- The system starts.
- When the local user made some changes.
- After an auto-merge happened.
- After a time interval.

### Content of Sync Interest
- Pairs of (branch, HEAD) + changes-heads
- Branches included
  - `refs/meta/*`
  - `refs/bmeta/<code-branch>`
  - `refs/users/<__>/<uid>`
  - `refs/groups/<__>/<gid>`
  - `refs/projects/catalog`
  - `refs/changes-hash`: A virtual branch, containing a hash on change-head-list.
- Branches excluded
  - `refs/local/*`: not necessary
  - `refs/heads/<code-branch>`: covered by bmeta
  - `refs/for/<code-branch>`: not necessary
  - `refs/changes/*`: too many  ???
- Change-head-list
  - Contains `refs/changes/<__>/<Change-ID>/meta` for every open change.
  - Should be accessible under `[PREFIX]/project/<PID>/objects/<changes-hash>/<seg=i>`.

### When receiving a Sync Interest
1. Cache new commits into local storage, like `/local`.
2. Fetch objects into local branches starting with `refs/local`.
3. Security check.
4. Merge into target branch.

Details: TBD

## Git Remote Helper
I realized this is not limited to NDN protocol.

## GitSync CLI
TBD

## Git Diff Textconv
Convert between TLV and JSON. (+ calculate hash name?)

## Plugins
Left for future work.
