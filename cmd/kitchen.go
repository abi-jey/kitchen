package cmd

import (
    "fmt"

    "github.com/spf13/cobra"
)

// kitchenCmd represents the kitchen command
var kitchenCmd = &cobra.Command{
    Use:   "kitchen",
    Short: "A brief description of the kitchen command",
    Long: `A longer description that spans multiple lines.
Use kitchen <subcommand> <args>`,
}

// createCmd represents the create subcommand
var createCmd = &cobra.Command{
    Use:   "create",
    Short: "A brief description of the create subcommand",
    Long: `A longer description that spans multiple lines.
Use kitchen create <args>`,
    Run: func(cmd *cobra.Command, args []string) {
        fmt.Println("kitchen create called")
    },
}

func init() {
    // Add kitchenCmd as a subcommand to rootCmd
    rootCmd.AddCommand(kitchenCmd)

    // Add createCmd as a subcommand to kitchenCmd
    kitchenCmd.AddCommand(createCmd)
}