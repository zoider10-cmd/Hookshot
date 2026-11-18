// Background work of the back end (vk_jobs.cpp): shader translation and pipeline builds run on a few worker threads
// at below-normal priority while the replay goes on, after totk-pc-recomp's vk_pipeline.c background builds. A draw
// whose program or pipeline is not ready yet is left out of its frame, or waits for it (vk_draw.cpp decides).
#pragma once

#include <atomic>
#include <functional>
#include <memory>

namespace mkwvk {

/// (hookshot) A queued job that whoever takes it first runs: a worker, or the thread that must wait for it
struct JobClaim {
    std::atomic<bool> taken{false};
    std::function<void()> fn;
};
/// Queues fn as a job a waiter may take over (jobs_claim_run)
std::shared_ptr<JobClaim> jobs_push_claim(std::function<void()> fn, bool urgent = false);
/// Runs the job on this thread when no worker has taken it yet (true: it ran here). A draw that has to wait for its
/// pipeline builds it itself instead of waiting behind every job queued before it (RX 6600: 118 s frozen, 26 jobs queued)
bool jobs_claim_run(const std::shared_ptr<JobClaim>& c);

/// Queues fn for a worker (urgent: ahead of the others, for work a draw waits on)
/// flag: what the job sets when it is done. A jobs_wait on it while the job is still queued runs the job there and then
/// on_failure: publishes the resource's failed/completed state if fn throws; must not throw.
/// A completion flag alone does not imply success: its resource must describe the failure too.
void jobs_push(std::function<void()> fn, bool urgent = false, const std::atomic<bool>* flag = nullptr,
               std::function<void()> on_failure = {});
/// Queues fn for the one thread that runs such jobs one at a time, in order (first: ahead of the others not queued first)
void jobs_push_serial(std::function<void()> fn, std::function<void()> on_failure = {}, bool first = false);
/// Waits until flag is set by a job (which calls jobs_notify after setting it). Its job still queued (pushed with flag) is
/// taken out and run on this thread first, so it runs once and never waits behind the queue: true when it ran here
bool jobs_wait(const std::atomic<bool>& flag);
bool jobs_steal(const std::atomic<bool>& flag);   // (Mako §78: a queued job for that flag run here, now)
/// Waits at most ms for flag, without running a queued job on this thread; whether it was set
bool jobs_wait_for(const std::atomic<bool>& flag, double ms);
/// (hookshot) Moves flag's job, still queued, to the queue's front, for the next free worker; whether it was queued
bool jobs_hurry(const std::atomic<bool>& flag);
void jobs_notify();
int jobs_pending();

} // namespace mkwvk
