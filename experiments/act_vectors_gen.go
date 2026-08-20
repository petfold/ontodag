// Vector generator for experiments/act_crypto_spike.py — runs INSIDE a
// checkout of github.com/ethersphere/bee (tested at v2.8.1):
//
//     mkdir bee/actvectors_main && cp act_vectors_gen.go bee/actvectors_main/main.go
//     cd bee && go run ./actvectors_main
//
// Kept here (not in the bee tree) so the pinned vectors in the spike are
// reproducible from source without patching upstream.
// Vector generator for ontodag's act-categories crypto spike: prints the
// deterministic ACT quantities for fixed keys, straight from Bee's own
// packages, so a Python reimplementation can be pinned bit-for-bit.
package main

import (
	"encoding/binary"
	"encoding/hex"
	"fmt"

	"github.com/ethersphere/bee/v2/pkg/accesscontrol"
	"github.com/ethersphere/bee/v2/pkg/crypto"
	"github.com/ethersphere/bee/v2/pkg/encryption"
	"golang.org/x/crypto/sha3"
)

func keyFromSeed(seed uint64) []byte {
	b := make([]byte, 32)
	binary.BigEndian.PutUint64(b[24:], seed)
	return b
}

func emit(label string, granteeSeed, publisherSeed uint64) {
	grantee := crypto.Secp256k1PrivateKeyFromBytes(keyFromSeed(granteeSeed))
	publisher := crypto.Secp256k1PrivateKeyFromBytes(keyFromSeed(publisherSeed))
	session := accesscontrol.NewDefaultSession(grantee)

	// Raw shared-x (nonce-less) — exposes Go's big.Int.Bytes() stripping.
	rawX, _ := session.Key(&publisher.PublicKey, nil)
	keys, _ := session.Key(&publisher.PublicKey,
		[][]byte{{0}, {1}})

	accessKey, _ := hex.DecodeString(
		"8abf1502f557f15026716030fb6384792583daf39608a3cd02ff2f47e9bc6e49")
	wrapped, _ := encryption.New(encryption.Key(keys[1]), 0, 0,
		sha3.NewLegacyKeccak256).Encrypt(accessKey)
	ref, _ := hex.DecodeString(
		"39a5ea87b141fe44aa609c3327ecd896c0e2122897f5f4bbacf74db1033c5559" +
			"0000000000000000000000000000000000000000000000000000000000000001")
	encRef, _ := encryption.New(accessKey, 0, 0,
		sha3.NewLegacyKeccak256).Encrypt(ref)

	fmt.Printf("%s:\n", label)
	fmt.Printf("  grantee_priv:   %x\n", keyFromSeed(granteeSeed))
	fmt.Printf("  publisher_priv: %x\n", keyFromSeed(publisherSeed))
	fmt.Printf("  publisher_pub:  %x\n",
		crypto.EncodeSecp256k1PublicKey(&publisher.PublicKey))
	fmt.Printf("  shared_x_bytes: %x (len %d)\n", rawX[0], len(rawX[0]))
	fmt.Printf("  lookup_key:     %x\n", keys[0])
	fmt.Printf("  ak_decrypt_key: %x\n", keys[1])
	fmt.Printf("  wrapped_ak:     %x\n", wrapped)
	fmt.Printf("  encrypted_ref:  %x\n", encRef)
}

func main() {
	emit("vector1", 42, 7)
	// Hunt a pair whose shared x-coordinate has a leading zero byte —
	// the big.Int.Bytes() stripping trap made flesh.
	for seed := uint64(1); seed < 4000; seed++ {
		grantee := crypto.Secp256k1PrivateKeyFromBytes(keyFromSeed(seed))
		publisher := crypto.Secp256k1PrivateKeyFromBytes(keyFromSeed(seed + 100000))
		session := accesscontrol.NewDefaultSession(grantee)
		rawX, _ := session.Key(&publisher.PublicKey, nil)
		if len(rawX[0]) < 32 {
			emit(fmt.Sprintf("vector2 (short x, seeds %d/%d)",
				seed, seed+100000), seed, seed+100000)
			return
		}
	}
	fmt.Println("no short-x pair found in range")
}
